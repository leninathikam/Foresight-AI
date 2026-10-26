from __future__ import annotations

import pytest

from foresight.branching import ActuatorSettings, compare_futures, estimate_state, wilson_interval
from foresight.prediction import RiskEngine
from foresight.simulation import (
    ContinueOperation,
    IncreaseCooling,
    ReduceSpeed,
    ScenarioId,
    ScheduleInspection,
    canonical_episode,
)
from foresight.telemetry import TelemetryStream
from foresight.verification import Proposal, verify


def _actuators(stream: TelemetryStream) -> ActuatorSettings:
    s = stream.twin.state
    return ActuatorSettings(
        load_multiplier=s.load_multiplier, speed_setpoint=s.speed_setpoint, aux_boost=s.aux_boost
    )


@pytest.fixture(scope="module")
def cooling_case(small_bundle_module):
    stream = TelemetryStream(canonical_episode(ScenarioId.COOLING_DEGRADATION))
    engine = RiskEngine(small_bundle_module)
    for _ in range(100):
        stream.advance(60)
        assessment = engine.assess(list(stream.window))
    est = estimate_state(list(stream.window)[-360:], _actuators(stream))
    comp = compare_futures(
        [
            ReduceSpeed(fraction=0.3),
            ScheduleInspection(delay_minutes=10),
            IncreaseCooling(boost=0.4),
        ],
        estimate=est,
        horizon_min=180,
        n_members=8,
    )
    return stream, assessment, est, comp


@pytest.fixture(scope="module")
def small_bundle_module(request):
    return request.getfixturevalue("small_bundle")


def test_wilson_interval_bounds():
    lo, hi = wilson_interval(0, 8)
    assert lo == 0 and 0.3 < hi < 0.35
    lo, hi = wilson_interval(8, 8)
    assert hi == 1 and 0.65 < lo < 0.7


def test_estimator_recovers_hidden_cooling_state(cooling_case):
    stream, _, est, _ = cooling_case
    true_eta = stream.twin.state.cooling_efficiency
    assert abs(est.cooling_efficiency - true_eta) < 0.12
    assert est.cooling_trend_per_h < -0.15  # true fouling rate is -0.32 / h
    assert est.bearing_damage < 0.15


def test_branches_share_initial_state_and_include_baseline(cooling_case):
    _, _, _, comp = cooling_case
    assert comp.branches[0].branch_id == "baseline"
    assert comp.branches[0].action == {"type": "continue_operation"}
    assert len(comp.branches) == 4
    assert all(b.n_members == 8 for b in comp.branches)
    # Same t0 and same horizon for every branch.
    lengths = {len(b.temperature_band.t_min) for b in comp.branches}
    assert lengths == {180}
    assert comp.estimate is not None and comp.state_source == "estimated"


def test_outcomes_differ_by_intervention(cooling_case):
    _, _, _, comp = cooling_case
    base = comp.branch_for_action(ContinueOperation())
    insp = comp.branch_for_action(ScheduleInspection(delay_minutes=10))
    assert base.failure_incidence == 1.0
    assert insp.failure_incidence == 0.0
    assert insp.objective < base.objective
    assert comp.ranking[0] == insp.branch_id


def test_verifier_rejects_unsafe_speed_reduction(cooling_case):
    stream, assessment, _, comp = cooling_case
    res = verify(Proposal(action=ReduceSpeed(fraction=0.3)), comp, assessment, now_s=stream.t_s)
    assert res.verdict == "rejected"
    failed = {c.name for c in res.checks if c.status == "fail"}
    assert {"temperature_limit", "failure_risk"} <= failed


def test_verifier_accepts_inspection_and_requires_approval(cooling_case):
    stream, assessment, _, comp = cooling_case
    res = verify(
        Proposal(action=ScheduleInspection(delay_minutes=10), claimed_failure_mode="thermal"),
        comp,
        assessment,
        now_s=stream.t_s,
    )
    assert res.verdict in ("accepted", "accepted_with_warnings")
    assert res.requires_human_approval


def test_verifier_rejects_unsimulated_and_infeasible_actions(cooling_case):
    stream, assessment, _, comp = cooling_case
    unsimulated = verify(
        Proposal(action=IncreaseCooling(boost=0.25)), comp, assessment, now_s=stream.t_s
    )
    assert unsimulated.verdict == "rejected"
    assert any(c.name == "simulation_complete" and c.status == "fail" for c in unsimulated.checks)

    over_capacity = verify(
        Proposal(action=IncreaseCooling(boost=0.8)), comp, assessment, now_s=stream.t_s
    )
    assert over_capacity.verdict == "rejected"

    late = verify(
        Proposal(action=ScheduleInspection(delay_minutes=400)), comp, assessment, now_s=stream.t_s
    )
    assert late.verdict == "rejected"


def test_verifier_rejects_stale_simulation_and_fabricated_evidence(cooling_case):
    stream, assessment, _, comp = cooling_case
    action = ScheduleInspection(delay_minutes=10)
    stale = verify(Proposal(action=action), comp, assessment, now_s=stream.t_s + 3600)
    assert stale.verdict == "rejected"
    fake = verify(
        Proposal(action=action, cited_evidence_ids=["obs:made_up_sensor"]),
        comp,
        assessment,
        now_s=stream.t_s,
        known_evidence_ids={e.id for e in assessment.evidence},
    )
    assert fake.verdict == "rejected"
    assert any(c.name == "evidence_exists" and c.status == "fail" for c in fake.checks)


def test_verifier_flags_inconsistent_failure_mode(cooling_case):
    stream, assessment, _, comp = cooling_case
    res = verify(
        Proposal(action=ScheduleInspection(delay_minutes=10), claimed_failure_mode="bearing"),
        comp,
        assessment,
        now_s=stream.t_s,
    )
    consistency = next(c for c in res.checks if c.name == "evidence_consistency")
    assert consistency.status == "warn"


def test_branching_is_reproducible(cooling_case):
    _, _, est, comp = cooling_case
    again = compare_futures(
        [
            ReduceSpeed(fraction=0.3),
            ScheduleInspection(delay_minutes=10),
            IncreaseCooling(boost=0.4),
        ],
        estimate=est,
        horizon_min=180,
        n_members=8,
    )
    assert [b.objective for b in again.branches] == [b.objective for b in comp.branches]
