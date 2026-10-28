from __future__ import annotations

import math

import pytest

from foresight.simulation import (
    ControlledShutdown,
    IncreaseCooling,
    MotorTwin,
    ReduceLoad,
    ReduceSpeed,
    ScenarioId,
    ScheduleInspection,
    canonical_episode,
    run_episode,
    sample_episode,
)


def _run(twin: MotorTwin, seconds: float):
    out = None
    for _ in range(int(seconds / 5)):
        out = twin.step()
    return out


def test_episode_is_deterministic_for_fixed_seed():
    cfg = canonical_episode(ScenarioId.COOLING_DEGRADATION)
    a, _, _ = run_episode(cfg)
    b, _, _ = run_episode(cfg)
    assert a == b


def test_different_seeds_differ():
    a, _, _ = run_episode(
        canonical_episode(ScenarioId.HEALTHY, seed=1).model_copy(update={"duration_s": 600})
    )
    b, _, _ = run_episode(
        canonical_episode(ScenarioId.HEALTHY, seed=2).model_copy(update={"duration_s": 600})
    )
    assert a != b


def test_sample_episode_is_reproducible():
    assert sample_episode(ScenarioId.OVERLOAD, 5) == sample_episode(ScenarioId.OVERLOAD, 5)
    assert sample_episode(ScenarioId.OVERLOAD, 5) != sample_episode(ScenarioId.OVERLOAD, 6)


def test_healthy_motor_does_not_fail_and_is_in_plausible_range():
    readings, _truths, twin = run_episode(canonical_episode(ScenarioId.HEALTHY))
    assert not twin.state.failed
    temps = [r.temperature_c for r in readings]
    assert min(temps) > 80 and max(temps) < 120
    assert max(r.vibration_mm_s for r in readings) < 1.8  # ISO zone A/B for a healthy machine


@pytest.mark.parametrize(
    ("scenario", "mode"),
    [
        (ScenarioId.COOLING_DEGRADATION, "thermal"),
        (ScenarioId.BEARING_DETERIORATION, "bearing"),
        (ScenarioId.OVERLOAD, "thermal"),
    ],
)
def test_fault_scenarios_reach_measurable_failure(scenario, mode):
    _, truths, twin = run_episode(canonical_episode(scenario))
    assert twin.state.failed and twin.state.failure_mode == mode
    assert truths[-1].failed
    assert 60 * 60 < twin.state.failure_time_s < 5 * 3600


def test_steady_state_matches_thermal_balance():
    twin = MotorTwin(canonical_episode(ScenarioId.HEALTHY))
    out = twin.true_outputs()
    rise = twin.state.temperature_c - twin.state.ambient_c
    assert math.isclose(rise, out.losses_w / out.conductance_w_per_k, rel_tol=1e-6)


def test_clone_shares_disturbances_and_reseed_changes_them():
    twin = MotorTwin(canonical_episode(ScenarioId.HEALTHY))
    _run(twin, 600)
    a, b, c = twin.clone(), twin.clone(), twin.clone(reseed=123)
    ra = [a.step()[0] for _ in range(50)]
    rb = [b.step()[0] for _ in range(50)]
    rc = [c.step()[0] for _ in range(50)]
    assert ra == rb
    assert ra != rc


def _fails_within(twin: MotorTwin, hours: float) -> bool:
    for _ in range(int(hours * 3600 / 5)):
        twin.step()
        if twin.state.failed:
            return True
    return False


def test_interventions_change_outcomes_with_matched_noise():
    twin = MotorTwin(canonical_episode(ScenarioId.OVERLOAD))
    _run(twin, 50 * 60)
    base, reduced, stopped = twin.clone(), twin.clone(), twin.clone()
    reduced.apply_action(ReduceLoad(fraction=0.3))
    stopped.apply_action(ControlledShutdown())
    assert _fails_within(base, 3)
    assert not _fails_within(reduced, 3)
    assert not _fails_within(stopped, 3)
    assert stopped.state.downtime_s > 0


def test_reducing_speed_reduces_self_ventilation_at_constant_torque():
    twin = MotorTwin(canonical_episode(ScenarioId.HEALTHY))
    slow = twin.clone()
    slow.apply_action(ReduceSpeed(fraction=0.4))
    _run(twin, 3 * 3600)
    _run(slow, 3 * 3600)
    assert slow.state.temperature_c > twin.state.temperature_c


def test_aux_cooling_is_capped_by_capacity():
    twin = MotorTwin(canonical_episode(ScenarioId.HEALTHY))
    twin.apply_action(IncreaseCooling(boost=0.9))
    assert twin.state.aux_boost == pytest.approx(twin.params.max_aux_cooling_boost)


def test_inspection_repairs_root_causes():
    twin = MotorTwin(canonical_episode(ScenarioId.BEARING_DETERIORATION))
    _run(twin, 120 * 60)
    assert twin.state.bearing_health < 0.8
    twin.apply_action(ScheduleInspection(delay_minutes=0))
    _run(twin, 4 * 3600)
    assert twin.state.bearing_replacements == 1
    assert twin.state.bearing_health > 0.95
    assert not twin.state.failed
