from __future__ import annotations

import numpy as np
import pytest

from foresight.branching import ActuatorSettings, compare_futures, estimate_state
from foresight.branching.estimation import slope_standard_error
from foresight.evaluation.agent_eval import carry_over_live_blocks
from foresight.evaluation.counterfactual import _fault_onset_min, _fault_state, _summarise
from foresight.simulation import ScenarioId, ScheduleInspection, canonical_episode
from foresight.telemetry import TelemetryStream
from foresight.verification import assess_information_value


def _estimate(scenario: ScenarioId, minutes: int = 100):
    stream = TelemetryStream(canonical_episode(scenario))
    stream.advance(minutes * 60)
    return estimate_state(list(stream.window)[-720:], ActuatorSettings())


@pytest.fixture(scope="module")
def cooling_estimate():
    return _estimate(ScenarioId.COOLING_DEGRADATION)


@pytest.fixture(scope="module")
def healthy_estimate():
    return _estimate(ScenarioId.HEALTHY)


def test_slope_standard_error_matches_ols():
    x = np.arange(10.0)
    y = 2.0 * x + np.array([0.1, -0.2, 0.0, 0.3, -0.1, 0.2, -0.3, 0.1, 0.0, -0.1])
    resid = y - np.polyval(np.polyfit(x, y, 1), x)
    expected = np.sqrt(resid @ resid / 8 / np.sum((x - x.mean()) ** 2))
    assert slope_standard_error(x, y) == pytest.approx(expected)
    assert slope_standard_error(x[:2], y[:2]) == float("inf")


def test_real_fouling_trend_is_statistically_supported(cooling_estimate):
    se = cooling_estimate.cooling_trend_se_per_h
    assert se is not None
    assert -cooling_estimate.cooling_trend_per_h / se > 2.0


def test_trends_are_unidentifiable_right_after_a_restart():
    stream = TelemetryStream(canonical_episode(ScenarioId.COOLING_DEGRADATION))
    stream.advance(100 * 60)
    stream.apply_action(ScheduleInspection(delay_minutes=0))
    stream.advance((90 + 10) * 60)
    est = estimate_state(list(stream.window), ActuatorSettings())
    assert est.cooling_trend_se_per_h is None and est.load_trend_se_per_h is None
    assert est.cooling_trend_per_h == 0.0


def test_supported_trend_acts_now(cooling_estimate):
    ia = assess_information_value(cooling_estimate)
    assert ia.decision == "act_now"
    assert ia.unsupported_trends == []
    assert next(t for t in ia.trends if t.name == "cooling_fouling").supported


def test_weak_trend_and_safe_wait_gathers_information(healthy_estimate):
    est = healthy_estimate.model_copy(
        update={"cooling_trend_per_h": -0.1, "cooling_trend_se_per_h": 0.08}
    )
    ia = assess_information_value(est)
    assert ia.decision == "gather_information", ia.summary
    assert ia.unsupported_trends == ["cooling_fouling"]
    assert ia.without_unsupported["failure_incidence"] == 0
    earliest = ia.waiting["earliest_failure_min"]
    assert earliest is None or earliest > ia.waiting["required_failure_free_min"]


def test_weak_trend_does_not_hide_risk_from_current_levels(healthy_estimate):
    est = healthy_estimate.model_copy(
        update={
            "cooling_efficiency": 0.3,
            "cooling_trend_per_h": -0.1,
            "cooling_trend_se_per_h": 0.08,
        }
    )
    ia = assess_information_value(est)
    assert ia.decision == "act_now"
    assert ia.summary.startswith("Risk remains without the unsupported trend")


def test_waiting_is_refused_when_a_weak_trend_could_still_fail_soon(healthy_estimate):
    est = healthy_estimate.model_copy(
        update={
            "temperature_c": 150.0,
            "cooling_trend_per_h": -0.5,
            "cooling_trend_se_per_h": 0.4,
        }
    )
    ia = assess_information_value(est)
    assert ia.decision == "act_now"


def test_standard_error_mode_widens_trend_spread(cooling_estimate):
    est = cooling_estimate.model_copy(update={"cooling_trend_se_per_h": 0.5})
    fixed = compare_futures([], estimate=est, n_members=8)
    wide = compare_futures([], estimate=est, n_members=8, trend_uncertainty="standard_error")
    spread = lambda c: np.std([m.peak_temperature_c for m in c.branches[0].members])  # noqa: E731
    assert wide.trend_uncertainty == "standard_error"
    assert spread(wide) > spread(fixed)


def test_offline_evaluation_keeps_committed_live_runs():
    previous = {
        "agent": {
            "deterministic": {"runs": 99},
            "live": {"status": "run", "runs": 126},
            "live_recheck": {"status": "run", "runs": 28},
            "skipped": {"status": "not_run"},
        }
    }
    merged = carry_over_live_blocks(
        {"deterministic": {"runs": 1}, "live": {"status": "not_run"}}, previous
    )
    assert merged["deterministic"] == {"runs": 1}
    assert merged["live"]["runs"] == 126 and merged["live_recheck"]["runs"] == 28
    assert "skipped" not in merged
    fresh = carry_over_live_blocks({"live": {"status": "run", "runs": 7}}, previous)
    assert fresh["live"]["runs"] == 7


def test_counterfactual_separates_latent_faults():
    assert _fault_onset_min(canonical_episode(ScenarioId.HEALTHY)) is None
    onset = _fault_onset_min(canonical_episode(ScenarioId.BEARING_DETERIORATION))
    assert onset == 20.0
    assert _fault_state(None, 60) == "no_fault"
    assert _fault_state(onset, 10) == "latent"
    assert _fault_state(onset, 60) == "active"


def test_counterfactual_scores_count_false_safe_branches():
    def row(p_hat, outcomes):
        return {
            "action": "a",
            "p_hat": p_hat,
            "outcomes": outcomes,
            "p_ref": float(np.mean(outcomes)),
            "peak_in_band": 0.5,
            "peak_median_error_k": 1.0,
        }

    points = [
        {
            "rows": {
                "fixed": [row(0.0, [0, 0, 0, 0]), row(0.0, [1, 0, 0, 0]), row(1.0, [1, 1, 1, 1])]
            },
            "decision": {"fixed": {"chosen": "x", "reference_best": "x", "regret_usd": 0.0}},
        }
    ]
    s = _summarise(points, "fixed")
    assert s["predicted_safe_branches"] == 2 and s["false_safe_branches"] == 1
    assert s["false_safe_mean_true_failure_rate"] == 0.25
    assert s["brier"] == pytest.approx(1 / 12, abs=1e-4)
    assert s["decision_matches_reference_best"] == 1
