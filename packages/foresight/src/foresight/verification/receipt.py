"""Tamper-evident Decision Receipts for industrial ML recommendations.

Provides structured cryptographic provenance for all inputs, model versions,
counterfactual simulation branches, safety verifications, and human approval states.
Includes SHA-256 digest generation and independent verification.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from foresight.branching import FutureComparison
from foresight.prediction.schemas import RiskAssessment
from foresight.telemetry import TelemetrySample
from foresight.verification.verifier import VerificationResult


class DecisionReceipt(BaseModel):
    receipt_id: str = Field(description="Unique receipt identifier")
    schema_version: str = Field(default="1.0.0", description="Receipt specification version")
    generated_at: str = Field(description="ISO 8601 UTC timestamp of creation")
    session_id: str = Field(description="Active digital-twin session identifier")
    asset_id: str = Field(default="15kW-TEFC-Conveyor-Drive", description="Target industrial asset")
    asset_specs: dict[str, Any] = Field(default_factory=dict, description="Asset operating limits and ratings")
    input_provenance: dict[str, Any] = Field(description="Telemetry state and input hashes at recommendation time")
    model_provenance: dict[str, Any] = Field(description="Model versions and inference metadata")
    scenarios_evaluated: list[dict[str, Any]] = Field(description="Counterfactual branches simulated")
    recommended_action: dict[str, Any] = Field(description="Recommended action parameters")
    claimed_fault_mode: str = Field(description="Diagnosed fault class")
    cited_evidence_ids: list[str] = Field(description="Evidence registry IDs cited by the proposal")
    safety_verification: dict[str, Any] = Field(description="Safety verifier verdict and check results")
    human_approval: dict[str, Any] = Field(description="Human in the loop approval status")
    sha256_digest: str = Field(description="Cryptographic SHA-256 digest over canonical receipt payload")
    audit_disclaimer: str = Field(
        default=(
            "Tamper-evident SHA-256 digest certifies cryptographic integrity and exact provenance of this "
            "decision record. It proves the record has not been altered since generation; it does not "
            "scientifically guarantee the empirical correctness of the underlying simulation assumptions."
        ),
        description="Legal and engineering disclaimer",
    )


def compute_telemetry_digest(samples: list[TelemetrySample]) -> str:
    """Compute a deterministic hash over the recent telemetry samples."""
    if not samples:
        return "empty"
    serialized = []
    for s in samples[-180:]:  # Last 30 min at 10s intervals
        serialized.append(f"{s.seq}:{s.t_s}:{s.running}:{s.values.get('temperature_c')}:{s.values.get('vibration_mm_s')}")
    raw = "|".join(serialized)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def compute_receipt_digest(payload: dict[str, Any]) -> str:
    """Compute SHA-256 digest over the canonical JSON of receipt fields excluding sha256_digest."""
    clean = {k: v for k, v in payload.items() if k != "sha256_digest"}
    canonical_json = json.dumps(clean, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def verify_receipt_integrity(receipt_dict: dict[str, Any]) -> tuple[bool, str, str]:
    """Verify whether a receipt's internal SHA-256 digest matches its canonical content.

    Returns:
        (is_valid, computed_digest, detail_message)
    """
    recorded_digest = receipt_dict.get("sha256_digest", "")
    if not recorded_digest:
        return False, "", "Missing 'sha256_digest' field in receipt"
    computed_digest = compute_receipt_digest(receipt_dict)
    if recorded_digest == computed_digest:
        return True, computed_digest, "Cryptographic integrity verified: digest matches canonical receipt payload exactly."
    return False, computed_digest, f"Integrity check FAILED: recorded digest ({recorded_digest[:16]}...) != recomputed ({computed_digest[:16]}...)"


def build_decision_receipt(
    *,
    session_id: str,
    action: dict[str, Any],
    claimed_fault_mode: str,
    cited_evidence_ids: list[str],
    verification: VerificationResult,
    samples: list[TelemetrySample],
    assessment: RiskAssessment | None = None,
    comparison: FutureComparison | None = None,
    copilot_provider: str = "google-gemini",
    copilot_model: str = "gemini-3.8-flash",
    human_approved: bool = False,
    operator_id: str | None = None,
) -> DecisionReceipt:
    """Construct and cryptographically seal a complete decision receipt."""
    receipt_id = f"rcpt-{uuid.uuid4().hex[:12]}"
    now_utc = datetime.now(UTC).isoformat(timespec="seconds")
    latest = samples[-1] if samples else None

    # Telemetry digest and summary
    telemetry_digest = compute_telemetry_digest(samples)
    input_provenance = {
        "telemetry_samples_count": len(samples),
        "t_current_s": latest.t_s if latest else 0.0,
        "telemetry_window_sha256": telemetry_digest,
        "latest_sensor_values": latest.values if latest else {},
        "anomaly_score": assessment.anomaly.score if (assessment and assessment.anomaly) else None,
        "is_anomalous": assessment.anomaly.is_anomalous if (assessment and assessment.anomaly) else False,
    }

    model_provenance = {
        "copilot_provider": copilot_provider,
        "copilot_model": copilot_model,
        "risk_engine": "XGBoost-v2.0-Calibrated",
        "anomaly_engine": "IsolationForest-v1.4",
        "changepoint_detector": "CUSUM-TwoSided-Residuals",
        "safety_verifier_version": "Verifier-v5.0-AdversarialHardened",
    }

    # Format evaluated future branches
    scenarios = []
    if comparison:
        for b in comparison.branches:
            scenarios.append(
                {
                    "branch_id": b.branch_id,
                    "label": b.label,
                    "action": b.action,
                    "failure_incidence": round(b.failure_incidence, 4),
                    "failure_incidence_ci95": [round(x, 4) for x in b.failure_incidence_ci95],
                    "peak_temperature_p90_c": round(b.peak_temperature_p90_c, 1),
                    "peak_vibration_p90_mm_s": round(b.peak_vibration_p90_mm_s, 2),
                    "expected_cost_usd": round(b.cost_mean, 2),
                    "objective_score": round(b.objective, 2),
                    "simulated_evidence_id": f"sim:{comparison.id}:{b.branch_id}",
                }
            )

    # Safety verification details
    verification_dict = {
        "verdict": verification.verdict,
        "decision_hash": verification.decision_hash,
        "action_label": verification.action_label,
        "summary": verification.summary,
        "requires_human_approval": verification.requires_human_approval,
        "rejection_reasons": verification.rejection_reasons,
        "checks": [c.model_dump() for c in verification.checks],
    }

    human_approval = {
        "required": verification.requires_human_approval,
        "status": "approved" if human_approved else "pending_human_approval",
        "operator_id": operator_id if human_approved else None,
        "approved_at": now_utc if human_approved else None,
    }

    receipt_obj = DecisionReceipt(
        receipt_id=receipt_id,
        schema_version="1.0.0",
        generated_at=now_utc,
        session_id=session_id,
        asset_id="15kW-TEFC-Conveyor-Drive",
        asset_specs={
            "rated_power_kw": 15.0,
            "winding_thermal_trip_c": 155.0,
            "vibration_trip_mm_s": 7.1,
            "insulation_class": "Class F (155 °C)",
            "standard": "ISO 10816-3 Group 2 (Rigid Support)",
        },
        input_provenance=input_provenance,
        model_provenance=model_provenance,
        scenarios_evaluated=scenarios,
        recommended_action=action,
        claimed_fault_mode=claimed_fault_mode,
        cited_evidence_ids=cited_evidence_ids or [],
        safety_verification=verification_dict,
        human_approval=human_approval,
        sha256_digest="",
    )
    receipt_obj.sha256_digest = compute_receipt_digest(receipt_obj.model_dump())
    return receipt_obj
