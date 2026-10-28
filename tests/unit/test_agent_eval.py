import pytest

from foresight.evaluation.agent_eval import Arm, bootstrap_mean_ci, parse_arms, summarise_runs


def _run(
    regret: float | None,
    case: str = "cooling_degradation@100min/s7",
    recommendation: str = "awaiting_approval",
    incidence: float = 0.0,
) -> dict:
    return {
        "case": case,
        "status": "completed",
        "recommendation": recommendation,
        "tool_calls": 5,
        "tool_errors": 0,
        "invalid_actions": 0,
        "rejections": 0,
        "latency_ms": 1000.0,
        "audit": None
        if regret is None
        else {"regret_vs_planner": regret, "agent_failure_incidence": incidence},
    }


def test_regret_summary_counts_only_audited_runs():
    summary = summarise_runs([_run(200.0), _run(-50.0), _run(0.0), _run(None)])
    assert summary["audited_runs"] == 3
    assert summary["mean_regret_vs_planner_usd"] == 50.0
    assert summary["runs_worse_than_planner"] == 1
    assert summary["runs_better_than_planner"] == 1
    lo, hi = summary["mean_regret_ci95"]
    assert lo <= 50.0 <= hi


def test_regret_summary_absent_without_audits():
    assert "audited_runs" not in summarise_runs([_run(None)])


def test_unsafe_choice_and_healthy_false_alarm_rates():
    runs = [
        _run(10.0, incidence=0.25),
        _run(0.0),
        _run(0.0, case="healthy@100min/s7", recommendation="awaiting_approval"),
        _run(None, case="healthy@100min/s7", recommendation="no_action_needed"),
    ]
    s = summarise_runs(runs)
    assert s["unsafe_choice"]["k"] == 1 and s["unsafe_choice"]["n"] == 3
    assert s["healthy_false_intervention"]["k"] == 1
    assert s["healthy_false_intervention"]["n"] == 2
    lo, hi = s["healthy_false_intervention"]["ci95"]
    assert 0.0 <= lo < 0.5 < hi <= 1.0


def test_bootstrap_ci_is_deterministic_and_needs_two_points():
    assert bootstrap_mean_ci([1.0]) is None
    assert bootstrap_mean_ci([1.0, 2.0, 9.0]) == bootstrap_mean_ci([1.0, 2.0, 9.0])


def test_parse_arms():
    assert parse_arms("meta:medium, fireworks:high") == [
        Arm("meta", "medium"),
        Arm("fireworks", "high"),
    ]
    assert Arm("fireworks", "low").key == "fireworks:low"
    with pytest.raises(ValueError):
        parse_arms("openai:medium")
    with pytest.raises(ValueError):
        parse_arms("meta")
