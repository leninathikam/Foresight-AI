"""Unit tests for the tamper-evident Decision Receipts engine."""

from __future__ import annotations

import pytest

from foresight.simulation import ScenarioId, canonical_episode
from foresight.telemetry import TelemetryStream
from foresight.verification import CheckResult, VerificationResult
from foresight.verification.receipt import (
    DecisionReceipt,
    build_decision_receipt,
    compute_receipt_digest,
    compute_telemetry_digest,
    verify_receipt_integrity,
)


@pytest.fixture
def sample_verification():
    return VerificationResult(
        verdict="accepted",
        action={"type": "reduce_load", "fraction": 0.25},
        action_label="Reduce load by 25%",
        checks=[
            CheckResult(name="temperature_envelope", status="pass", detail="Within 140 C limit", blocking=True),
            CheckResult(name="vibration_envelope", status="pass", detail="Within 6.1 mm/s limit", blocking=True),
        ],
        requires_human_approval=True,
        rejection_reasons=[],
        comparison_id="fc-sample-01",
        summary="Passed all blocking checks",
        decision_hash="a" * 64,
    )


@pytest.fixture
def telemetry_samples():
    stream = TelemetryStream(canonical_episode(ScenarioId.COOLING_DEGRADATION))
    for _ in range(30):
        stream.advance(10)
    return list(stream.window)


def test_build_decision_receipt(telemetry_samples, sample_verification):
    receipt = build_decision_receipt(
        session_id="sess_receipt_01",
        action={"type": "reduce_load", "fraction": 0.25},
        claimed_fault_mode="cooling_degradation",
        cited_evidence_ids=["obs:temperature_c", "obs:ambient_c"],
        verification=sample_verification,
        samples=telemetry_samples,
        copilot_provider="google-gemini",
        copilot_model="gemini-3.8-flash",
        human_approved=True,
        operator_id="OP-TEST-USER",
    )

    assert isinstance(receipt, DecisionReceipt)
    assert receipt.session_id == "sess_receipt_01"
    assert receipt.human_approval["status"] == "approved"
    assert receipt.human_approval["operator_id"] == "OP-TEST-USER"
    assert receipt.safety_verification["verdict"] == "accepted"
    assert len(receipt.sha256_digest) == 64

    # Verify that the digest passes integrity check
    valid, computed, msg = verify_receipt_integrity(receipt.model_dump())
    assert valid is True
    assert computed == receipt.sha256_digest


def test_receipt_tamper_detection(telemetry_samples, sample_verification):
    receipt = build_decision_receipt(
        session_id="sess_receipt_tamper",
        action={"type": "schedule_inspection", "delay_minutes": 15},
        claimed_fault_mode="bearing",
        cited_evidence_ids=["obs:vibration_mm_s"],
        verification=sample_verification,
        samples=telemetry_samples,
        human_approved=False,
    )

    receipt_dict = receipt.model_dump()
    valid, _, _ = verify_receipt_integrity(receipt_dict)
    assert valid is True

    # Tamper with the action payload (e.g. increase inspection delay)
    tampered_dict = dict(receipt_dict)
    tampered_dict["recommended_action"] = {"type": "schedule_inspection", "delay_minutes": 120}

    tampered_valid, computed_tampered, msg = verify_receipt_integrity(tampered_dict)
    assert tampered_valid is False
    assert computed_tampered != receipt.sha256_digest
    assert "FAILED" in msg

    # Tamper with approval status
    tampered_dict_2 = dict(receipt_dict)
    tampered_dict_2["human_approval"] = {"required": True, "status": "approved", "operator_id": "MALICIOUS"}
    tampered_valid_2, _, _ = verify_receipt_integrity(tampered_dict_2)
    assert tampered_valid_2 is False


def test_telemetry_digest_reproducibility(telemetry_samples):
    d1 = compute_telemetry_digest(telemetry_samples)
    d2 = compute_telemetry_digest(telemetry_samples)
    assert d1 == d2
    assert len(d1) == 64
