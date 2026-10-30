"""Adversarial regression and safety integrity tests for Verifier v5 bearing safeguards.

Explicitly verifies:
1. Reproduction of the discovered bearing derating failure (ReduceLoad(0.35) rejected).
2. Complete vibration trajectory evaluation across all time slices (not only scalar endpoint).
3. Preservation of legitimate safe interventions (ControlledShutdown, timely ScheduleInspection).
4. Physical units and ISO 10816-3 threshold consistency.
5. Distinction between statistical risk bounding and guaranteed physical safety.
"""

from __future__ import annotations

import pytest

from foresight.branching import (
    ActuatorSettings,
    Band,
    compare_futures,
    estimate_state,
)
from foresight.prediction import RiskEngine
from foresight.simulation import (
    ControlledShutdown,
    ReduceLoad,
    ScenarioId,
    ScheduleInspection,
    canonical_episode,
)
from foresight.telemetry import TelemetryStream
from foresight.verification import Proposal, verify, verify_independently


@pytest.fixture(scope="module")
def bearing_case_120min(request):
    """Reproduces the exact case from redteam_v4: bearing_deterioration@120min/s7."""
    bundle = request.getfixturevalue("small_bundle")
    stream = TelemetryStream(canonical_episode(ScenarioId.BEARING_DETERIORATION, seed=7))
    engine = RiskEngine(bundle)
    for _ in range(120):
        stream.advance(60)
        assessment = engine.assess(list(stream.window))
    s = stream.twin.state
    actuators = ActuatorSettings(
        load_multiplier=s.load_multiplier, speed_setpoint=s.speed_setpoint, aux_boost=s.aux_boost
    )
    est = estimate_state(list(stream.window)[-360:], actuators)
    comp = compare_futures(
        [
            ReduceLoad(fraction=0.35),
            ScheduleInspection(delay_minutes=10),
            ControlledShutdown(),
        ],
        estimate=est,
        horizon_min=180,
        n_members=8,
        base_seed=0,
    )
    return stream, assessment, est, comp


def test_reproduce_and_block_bearing_derating_failure(bearing_case_120min):
    """Verify that pure load derating (ReduceLoad 0.35) on bearing deterioration is blocked.

    In the red-team v4 audit, ReduceLoad(0.35) escaped a 16-member check but failed in audit
    because derating load cannot stop irreversible mechanical bearing spalling; vibration continues
    to rise into the ISO alarm/trip zone.
    """
    stream, assessment, _, comp = bearing_case_120min
    proposal = Proposal(
        action=ReduceLoad(fraction=0.35),
        claimed_failure_mode="bearing",
        cited_evidence_ids=["ml:diagnosis"],
        source="agent",
    )

    res = verify(proposal, comp, assessment, now_s=stream.t_s, confirmation=comp)

    # Must be rejected
    assert res.verdict == "rejected"
    failed_checks = {c.name: c for c in res.checks if c.status == "fail"}
    assert "vibration_trajectory" in failed_checks
    detail = failed_checks["vibration_trajectory"].detail
    assert "Bearing defect trajectory continues upward unabated" in detail
    assert "ISO alarm threshold" in detail
    assert "4.5" in detail


def test_preserves_legitimate_safe_interventions(bearing_case_120min):
    """Confirm that ControlledShutdown and timely ScheduleInspection still pass verification."""
    stream, assessment, _, comp = bearing_case_120min

    # 1. ControlledShutdown must be accepted
    shutdown_prop = Proposal(
        action=ControlledShutdown(),
        claimed_failure_mode="bearing",
        cited_evidence_ids=["ml:diagnosis"],
        source="agent",
    )
    res_shutdown = verify_independently(
        shutdown_prop,
        comp,
        assessment,
        now_s=stream.t_s,
    )
    assert res_shutdown.verdict in ("accepted", "accepted_with_warnings")
    assert res_shutdown.requires_human_approval is True

    # 2. ScheduleInspection(10 min) with lead time must be accepted
    insp_prop = Proposal(
        action=ScheduleInspection(delay_minutes=10),
        claimed_failure_mode="bearing",
        cited_evidence_ids=["ml:diagnosis"],
        source="agent",
    )
    res_insp = verify_independently(
        insp_prop,
        comp,
        assessment,
        now_s=stream.t_s,
    )
    assert res_insp.verdict in ("accepted", "accepted_with_warnings")
    assert res_insp.requires_human_approval is True


def test_vibration_trajectory_catches_intermediate_breach(bearing_case_120min):
    """Verify that an intermediate trajectory spike exceeding 6.1 mm/s is caught even if end state looks low."""
    stream, assessment, _, comp = bearing_case_120min
    fake_comp = comp.model_copy(deep=True)
    proposal = Proposal(
        action=ScheduleInspection(delay_minutes=10),
        claimed_failure_mode="thermal",
        source="agent",
    )
    branch = fake_comp.branch_for_action(proposal.action)
    assert branch is not None

    # Construct a synthetic trajectory where endpoint is safe (3.5 mm/s) but an intermediate point spikes to 6.5 mm/s
    t_min = list(range(0, 181))
    p90_vals = [2.0] * 50 + [6.5] + [3.5] * 130
    branch.vibration_band = Band(t_min=t_min, p10=[1.0] * 181, p50=[2.0] * 181, p90=p90_vals)

    res = verify(proposal, fake_comp, assessment, now_s=stream.t_s, confirmation=fake_comp)
    failed = {c.name: c for c in res.checks if c.status == "fail"}
    assert "vibration_trajectory" in failed
    assert "breaches safe operating limit" in failed["vibration_trajectory"].detail
    assert "6.50 mm/s" in failed["vibration_trajectory"].detail


def test_statistical_risk_disclaimer_in_confirmation(bearing_case_120min):
    """Verify that independent confirmation explicitly notes Monte Carlo bounds vs physical certainty."""
    stream, assessment, _, comp = bearing_case_120min
    prop = Proposal(
        action=ScheduleInspection(delay_minutes=10),
        claimed_failure_mode="thermal",
        source="agent",
    )
    res = verify_independently(prop, comp, assessment, now_s=stream.t_s)
    conf = next(c for c in res.checks if c.name == "independent_confirmation")
    assert conf.status == "pass"
    assert (
        "Monte Carlo samples cannot guarantee elimination of rare tail-risk events" in conf.detail
    )
    assert "bounds tail risk statistically" in conf.detail
    assert "ISO 10816-3 RMS" in conf.detail
