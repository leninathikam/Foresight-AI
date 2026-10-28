from __future__ import annotations

import numpy as np
import pytest

from foresight.branching import ActuatorSettings, estimate_state
from foresight.config import Settings
from foresight.evaluation.agent_eval import live_agent_metrics, summarise_runs
from foresight.evaluation.interventions import run_policy_episode
from foresight.evaluation.predictive import (
    evaluate_detection,
    evaluate_diagnosis,
    evaluate_risk,
    expected_calibration_error,
)
from foresight.prediction.changepoint import cusum
from foresight.prediction.dataset import assemble, simulate_episode_rows
from foresight.simulation import ScenarioId, ScheduleInspection, canonical_episode
from foresight.telemetry import TelemetryStream


def test_cusum_skip_and_upward_only():
    series = np.concatenate([np.full(30, 10.0), np.zeros(100), np.full(50, -5.0)])
    res = cusum(series, 0.0, 1.0, drift=0.5, threshold=8.0, skip=30, upward_only=True)
    assert res.alarm_index is None
    assert res.negative.max() > 8.0


def test_ece_is_zero_for_perfect_calibration():
    p = np.repeat([0.05, 0.95], 1000)
    y = np.concatenate([np.r_[np.ones(50), np.zeros(950)], np.r_[np.ones(950), np.zeros(50)]])
    assert expected_calibration_error(y, p) < 1e-9


def test_estimator_uses_only_data_since_restart():
    stream = TelemetryStream(canonical_episode(ScenarioId.COOLING_DEGRADATION))
    stream.advance(100 * 60)
    before = estimate_state(list(stream.window), ActuatorSettings())
    stream.apply_action(ScheduleInspection(delay_minutes=0))
    stream.advance((90 + 30) * 60)
    after = estimate_state(list(stream.window), ActuatorSettings())
    assert before.cooling_efficiency < 0.75
    assert after.cooling_efficiency > 0.85
    assert any("since the last restart" in n for n in after.notes)


@pytest.fixture(scope="module")
def tiny_test_set():
    return assemble(
        [simulate_episode_rows(sc, seed) for sc in ScenarioId for seed in range(2000, 2002)]
    )


def test_predictive_evaluation_structure(small_bundle, tiny_test_set):
    risk = evaluate_risk(small_bundle, tiny_test_set, tiny_test_set)
    for block in risk["horizons"].values():
        assert {"xgboost_calibrated", "logistic_regression", "alarm_threshold_rule"} <= set(
            block["methods"]
        )
        for m in block["methods"].values():
            assert m["pr_auc"] is None or 0.0 <= m["pr_auc"] <= 1.0
    det = evaluate_detection(small_bundle, tiny_test_set)
    assert det["cusum_any"]["faulted_episodes"] == 6
    diag = evaluate_diagnosis(small_bundle, tiny_test_set)
    assert len(diag["all_rows"]["confusion_matrix"]) == 4


def test_rule_policy_prevents_overload_failure(small_bundle):
    settings = Settings(MODEL_API_KEY=None)
    none = run_policy_episode(ScenarioId.OVERLOAD, 2001, "no_action", small_bundle, settings)
    rule = run_policy_episode(
        ScenarioId.OVERLOAD, 2001, "rule_inspect_on_alarm", small_bundle, settings
    )
    assert rule.interventions and rule.interventions[0]["action"]["type"] == "schedule_inspection"
    assert not rule.failed
    assert rule.cost_total <= none.cost_total


def test_live_agent_eval_is_not_faked_without_key(small_bundle):
    out = live_agent_metrics(small_bundle, Settings(MODEL_API_KEY=None), run=True)
    assert out["status"] == "not_run"


def test_summarise_runs_counts():
    runs = [
        {
            "status": "completed",
            "recommendation": "awaiting_approval",
            "tool_calls": 4,
            "tool_errors": 1,
            "invalid_actions": 0,
            "rejections": 1,
            "latency_ms": 10.0,
        },
        {
            "status": "failed",
            "recommendation": None,
            "tool_calls": 2,
            "tool_errors": 0,
            "invalid_actions": 1,
            "rejections": 0,
            "latency_ms": 30.0,
        },
    ]
    s = summarise_runs(runs)
    assert s["completion_rate"] == 0.5
    assert s["tool_success_rate"] == round(1 - 1 / 6, 4)
    assert s["verifier_rejections"] == 1 and s["invalid_actions"] == 1
