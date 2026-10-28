"""Closed-loop intervention evaluation on held-out episodes.

Each policy runs the same randomized test episode (same seed, same disturbances) from t=0.
Policies only see telemetry and model outputs, except ``foresight_oracle`` which plans from the
hidden true state as an upper bound. Approval of recommended actions is *simulated* here
(auto-approved) because a human cannot sit in a batch evaluation; the live system requires it.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import asdict, dataclass, field

import numpy as np
from joblib import Parallel, delayed

from foresight.agents import AgentOrchestrator, AgentSnapshot
from foresight.branching import (
    ACTION_ADAPTER,
    AccountingStart,
    ActuatorSettings,
    account_costs,
    wilson_interval,
)
from foresight.config import Settings
from foresight.prediction.dataset import SPLIT_SEEDS
from foresight.prediction.models import RiskBundle, RiskEngine
from foresight.simulation import (
    DEFAULT_ECONOMICS,
    Action,
    ControlledShutdown,
    ReduceLoad,
    ScenarioId,
    ScheduleInspection,
    describe_action,
    sample_episode,
)
from foresight.telemetry import TelemetryStream

EPISODE_S = 6 * 3600.0
ASSESS_EVERY_S = 60.0
AGENT_EVERY_S = 300.0
AGENT_COOLDOWN_S = 30 * 60.0
MAX_INTERVENTIONS = 3
TRIGGER_RISK_60 = 0.2

POLICIES = (
    "no_action",
    "rule_derate",
    "rule_shutdown_on_alarm",
    "rule_inspect_on_alarm",
    "foresight_estimated",
    "foresight_oracle",
)
POLICY_NOTES = {
    "no_action": "Never intervene.",
    "rule_derate": "Alarm (≥130 °C or ≥4.5 mm/s) → reduce load 30 %; ≥145 °C or ≥6.5 mm/s → shutdown.",
    "rule_shutdown_on_alarm": "Alarm → controlled shutdown (stays down; fault left for later repair).",
    "rule_inspect_on_alarm": "Alarm → immediate inspection (strong maintenance-aware rule).",
    "foresight_estimated": "Risk-triggered agent (deterministic planner) → Future Branching from the "
    "telemetry-estimated state → verifier → auto-approved action.",
    "foresight_oracle": "Same loop, but branches simulate the hidden true state (upper bound).",
}


@dataclass
class EpisodeResult:
    scenario: str
    seed: int
    policy: str
    failed: bool
    failure_mode: str | None
    failure_time_min: float | None
    cost_total: float
    cost: dict
    downtime_h: float
    peak_temperature_c: float
    interventions: list[dict] = field(default_factory=list)
    agent_runs: list[dict] = field(default_factory=list)
    wall_s: float = 0.0


def _alarm(sample_values: dict) -> tuple[bool, bool]:
    t = sample_values.get("temperature_c")
    v = sample_values.get("vibration_mm_s")
    alarm = (t is not None and t >= 130.0) or (v is not None and v >= 4.5)
    trip = (t is not None and t >= 145.0) or (v is not None and v >= 6.5)
    return alarm, trip


def _actuators(stream: TelemetryStream) -> ActuatorSettings:
    s = stream.twin.state
    return ActuatorSettings(
        load_multiplier=s.load_multiplier, speed_setpoint=s.speed_setpoint, aux_boost=s.aux_boost
    )


def run_policy_episode(
    scenario: ScenarioId, seed: int, policy: str, bundle: RiskBundle, settings: Settings
) -> EpisodeResult:
    wall = time.perf_counter()
    config = sample_episode(scenario, seed, duration_s=EPISODE_S)
    stream = TelemetryStream(config)
    engine = RiskEngine(bundle)
    start = AccountingStart.of(stream.twin)
    interventions: list[dict] = []
    agent_runs: list[dict] = []
    rule_state = {"derated": False, "acted": False}
    last_agent_action_s = -np.inf
    peak_t = stream.twin.state.temperature_c

    def act(action: Action, source: str, note: str = "") -> None:
        stream.apply_action(action, source=source)
        interventions.append(
            {
                "t_min": round(stream.t_s / 60.0, 1),
                "action": ACTION_ADAPTER.dump_python(action, mode="json"),
                "label": describe_action(action),
                "note": note,
            }
        )

    while stream.t_s < EPISODE_S and not stream.twin.state.failed:
        stream.advance(ASSESS_EVERY_S)
        peak_t = max(peak_t, stream.twin.state.temperature_c)
        window = list(stream.window)
        if not window:
            continue
        latest = window[-1].values
        s = stream.twin.state
        if s.shutdown or (s.maintenance_until_s is not None and s.maintenance_until_s > s.t_s):
            continue
        alarm, trip = _alarm(latest)

        if policy == "rule_derate":
            if trip:
                act(ControlledShutdown(), "system", "trip-level reading")
            elif alarm and not rule_state["derated"]:
                rule_state["derated"] = True
                act(ReduceLoad(fraction=0.3), "system", "alarm reading")
        elif policy == "rule_shutdown_on_alarm" and alarm and not rule_state["acted"]:
            rule_state["acted"] = True
            act(ControlledShutdown(), "system", "alarm reading")
        elif policy == "rule_inspect_on_alarm" and alarm and len(interventions) < MAX_INTERVENTIONS:
            act(ScheduleInspection(delay_minutes=0), "system", "alarm reading")

        assessment = engine.assess(window)
        if not policy.startswith("foresight"):
            continue
        if round(stream.t_s) % round(AGENT_EVERY_S) != 0:
            continue
        if len(interventions) >= MAX_INTERVENTIONS:
            continue
        if stream.t_s - last_agent_action_s < AGENT_COOLDOWN_S:
            continue
        if not assessment.available:
            continue
        risk60 = next(hr.probability for hr in assessment.horizons if hr.horizon_min == 60)
        if risk60 < TRIGGER_RISK_60 and not (
            assessment.anomaly and assessment.anomaly.is_anomalous
        ):
            continue
        snapshot = AgentSnapshot(
            session_id=f"eval-{scenario.value}-{seed}",
            t_s=stream.t_s,
            samples=window[-720:],
            actuators=_actuators(stream),
            assessment=assessment,
            oracle_twin=stream.twin.clone(),
            planning_state_source="oracle" if policy == "foresight_oracle" else "estimated",
        )
        trace = asyncio.run(AgentOrchestrator(snapshot, settings).run())
        rec = trace.recommendation
        agent_runs.append(
            {
                "t_min": round(stream.t_s / 60.0, 1),
                "status": trace.status,
                "latency_ms": round(trace.latency_ms or 0.0, 1),
                "tool_calls": trace.usage.tool_calls,
                "tool_errors": trace.usage.tool_errors,
                "invalid_actions": trace.usage.invalid_actions,
                "rejections": len(trace.rejected),
                "rejected": [r.action_label for r in trace.rejected],
                "recommendation": rec.status if rec else None,
                "action": rec.action_label if rec else None,
                "error": trace.error,
            }
        )
        if rec and rec.status == "awaiting_approval" and rec.action:
            action = ACTION_ADAPTER.validate_python(rec.action)
            act(action, "agent", "auto-approved by evaluation harness")
            last_agent_action_s = stream.t_s

    cost, failed, ttf_min, _ = account_costs(stream.twin, start, EPISODE_S, DEFAULT_ECONOMICS)
    s = stream.twin.state
    return EpisodeResult(
        scenario=scenario.value,
        seed=seed,
        policy=policy,
        failed=failed,
        failure_mode=s.failure_mode if failed else None,
        failure_time_min=None if ttf_min is None else round(ttf_min, 1),
        cost_total=round(cost.total, 2),
        cost={k: round(v, 2) for k, v in cost.model_dump().items()},
        downtime_h=round((s.downtime_s - start.downtime_s) / 3600.0, 3),
        peak_temperature_c=round(peak_t, 2),
        interventions=interventions,
        agent_runs=agent_runs,
        wall_s=round(time.perf_counter() - wall, 2),
    )


def _summarise(results: list[EpisodeResult]) -> dict:
    n = len(results)
    k = sum(r.failed for r in results)
    costs = np.array([r.cost_total for r in results])
    return {
        "episodes": n,
        "failures": k,
        "failure_rate": round(k / n, 4) if n else None,
        "failure_rate_ci95": [round(x, 4) for x in wilson_interval(k, n)],
        "cost_mean": round(float(costs.mean()), 1) if n else None,
        "cost_median": round(float(np.median(costs)), 1) if n else None,
        "downtime_h_mean": round(float(np.mean([r.downtime_h for r in results])), 3),
        "interventions_mean": round(float(np.mean([len(r.interventions) for r in results])), 2),
        "peak_temperature_c_mean": round(
            float(np.mean([r.peak_temperature_c for r in results])), 1
        ),
    }


def evaluate_interventions(
    bundle: RiskBundle,
    seeds_per_scenario: int = 5,
    policies: tuple[str, ...] = POLICIES,
    n_jobs: int = -1,
) -> dict:
    settings = Settings(MODEL_API_KEY=None)
    seeds = list(SPLIT_SEEDS["test"])[:seeds_per_scenario]
    jobs = [(sc, sd, p) for sc in ScenarioId for sd in seeds for p in policies]
    start = time.perf_counter()
    results: list[EpisodeResult] = Parallel(n_jobs=n_jobs)(
        delayed(run_policy_episode)(sc, sd, p, bundle, settings) for sc, sd, p in jobs
    )
    by_policy: dict[str, dict] = {}
    for p in policies:
        rp = [r for r in results if r.policy == p]
        by_policy[p] = {
            "overall": _summarise(rp),
            "by_scenario": {
                sc.value: _summarise([r for r in rp if r.scenario == sc.value]) for sc in ScenarioId
            },
            "healthy_episodes_with_intervention": sum(
                1 for r in rp if r.scenario == "healthy" and r.interventions
            ),
        }
    paired = {}
    base = {(r.scenario, r.seed): r for r in results if r.policy == "no_action"}
    for p in policies:
        if p == "no_action" or not base:
            continue
        diffs = [
            r.cost_total - base[(r.scenario, r.seed)].cost_total
            for r in results
            if r.policy == p and (r.scenario, r.seed) in base
        ]
        paired[p] = {
            "mean_cost_change_vs_no_action": round(float(np.mean(diffs)), 1),
            "episodes_cheaper": int(sum(d < 0 for d in diffs)),
            "episodes_costlier": int(sum(d > 0 for d in diffs)),
        }
    return {
        "seeds": seeds,
        "scenarios": [sc.value for sc in ScenarioId],
        "episode_hours": EPISODE_S / 3600.0,
        "policy_notes": {p: POLICY_NOTES[p] for p in policies},
        "approval_note": "Recommended actions were auto-approved by the harness (simulation only).",
        "by_policy": by_policy,
        "paired_vs_no_action": paired,
        "episodes": [asdict(r) for r in results],
        "wall_s": round(time.perf_counter() - start, 1),
    }
