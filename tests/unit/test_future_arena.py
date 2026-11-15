"""Unit tests for the Future Arena 3-way counterfactual scenario simulator."""

from __future__ import annotations

import pytest

from foresight.branching import ActuatorSettings, estimate_state
from foresight.branching.arena import FutureArenaComparison, run_future_arena
from foresight.prediction import RiskEngine
from foresight.simulation import ScenarioId, canonical_episode
from foresight.telemetry import TelemetryStream


def _actuators(stream: TelemetryStream) -> ActuatorSettings:
    s = stream.twin.state
    return ActuatorSettings(
        load_multiplier=s.load_multiplier,
        speed_setpoint=s.speed_setpoint,
        aux_boost=s.aux_boost,
    )


@pytest.fixture
def motor_estimate(small_bundle):
    stream = TelemetryStream(canonical_episode(ScenarioId.COOLING_DEGRADATION))
    engine = RiskEngine(small_bundle)
    for _ in range(60):
        stream.advance(60)
        assessment = engine.assess(list(stream.window))
    est = estimate_state(list(stream.window)[-360:], _actuators(stream))
    return stream, assessment, est


def test_future_arena_returns_three_scenarios(motor_estimate):
    stream, assessment, est = motor_estimate
    comparison = run_future_arena(
        session_id="test_sess_01",
        t0_s=stream.t_s,
        estimate=est,
        assessment=assessment,
        horizon_min=120.0,
        members=4,
        base_seed=101,
        oracle_twin=stream.twin,
    )

    assert isinstance(comparison, FutureArenaComparison)
    assert comparison.session_id == "test_sess_01"
    assert len(comparison.scenarios) == 3

    scenario_ids = [s.scenario_id for s in comparison.scenarios]
    assert scenario_ids == ["continue_operating", "reduce_load", "planned_maintenance"]

    for sc in comparison.scenarios:
        assert sc.failure_incidence >= 0.0
        assert sc.failure_incidence <= 1.0
        assert sc.failure_incidence_ci95[0] <= sc.failure_incidence_ci95[1]
        assert sc.expected_cost_usd >= 0.0
        assert sc.safety_status in ("accepted", "accepted_with_warnings", "rejected")
        assert len(sc.evidence_id) > 0

    assert comparison.winner_scenario_id in scenario_ids
    assert len(comparison.recommendation_reason) > 0
    assert len(comparison.assumptions) >= 3


def test_future_arena_deterministic_replay(motor_estimate):
    stream, assessment, est = motor_estimate

    comp1 = run_future_arena(
        session_id="test_sess_replay",
        t0_s=stream.t_s,
        estimate=est,
        assessment=assessment,
        horizon_min=90.0,
        members=4,
        base_seed=4242,
    )

    comp2 = run_future_arena(
        session_id="test_sess_replay",
        t0_s=stream.t_s,
        estimate=est,
        assessment=assessment,
        horizon_min=90.0,
        members=4,
        base_seed=4242,
    )

    assert comp1.winner_scenario_id == comp2.winner_scenario_id
    for sc1, sc2 in zip(comp1.scenarios, comp2.scenarios, strict=True):
        assert sc1.scenario_id == sc2.scenario_id
        assert sc1.failure_incidence == sc2.failure_incidence
        assert sc1.peak_temperature_p90_c == sc2.peak_temperature_p90_c
        assert sc1.peak_vibration_p90_mm_s == sc2.peak_vibration_p90_mm_s
        assert sc1.expected_cost_usd == sc2.expected_cost_usd
        assert sc1.safety_status == sc2.safety_status
