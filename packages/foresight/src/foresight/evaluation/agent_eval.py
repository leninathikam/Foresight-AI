"""Agent reliability metrics: deterministic planner runs (always) and live model runs.

Live runs call real model endpoints (Meta Model API and/or Fireworks AI) and only happen when a
key is configured and the run is explicitly requested; they are never simulated. A live
evaluation is a set of *arms* (provider × reasoning effort), each run over the same cases with
the same snapshots, scored against the deterministic planner in a shared audit comparison.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import numpy as np

from foresight.agents import AgentOrchestrator, AgentSnapshot, ModelClient
from foresight.branching import (
    ACTION_ADAPTER,
    ActuatorSettings,
    compare_futures,
    estimate_state,
    wilson_interval,
)
from foresight.config import ProviderName, Settings
from foresight.prediction.models import RiskBundle, RiskEngine
from foresight.prediction.schemas import RiskAssessment
from foresight.simulation import ScenarioId, canonical_episode
from foresight.telemetry import TelemetryStream

# (scenario, episode seed, minute at which the agent is asked). Two disturbance seeds per fault
# (7 = the demo seed, 2011 = a test-split noise seed) plus a healthy control, which should not
# trigger an intervention.
LIVE_CASES: tuple[tuple[ScenarioId, int, int], ...] = (
    (ScenarioId.COOLING_DEGRADATION, 7, 100),
    (ScenarioId.COOLING_DEGRADATION, 2011, 100),
    (ScenarioId.BEARING_DETERIORATION, 7, 120),
    (ScenarioId.BEARING_DETERIORATION, 2011, 120),
    (ScenarioId.OVERLOAD, 7, 60),
    (ScenarioId.OVERLOAD, 2011, 60),
    (ScenarioId.HEALTHY, 7, 100),
)

AUDIT_SEED = 777
AUDIT_MEMBERS = 16
BOOTSTRAP_SEED = 0


@dataclass(frozen=True)
class Arm:
    provider: ProviderName
    effort: str

    @property
    def key(self) -> str:
        return f"{self.provider}:{self.effort}"


def parse_arms(spec: str) -> list[Arm]:
    """``"meta:medium,fireworks:medium"`` → arms."""
    arms = []
    for part in spec.split(","):
        provider, _, effort = part.strip().partition(":")
        if provider not in ("meta", "fireworks") or not effort:
            raise ValueError(f"Bad arm {part!r}; expected provider:effort, e.g. meta:medium")
        arms.append(Arm(provider, effort))  # type: ignore[arg-type]
    return arms


def _stats(values: list[float]) -> dict:
    if not values:
        return {"p50": None, "p95": None}
    a = np.array(values)
    return {"p50": round(float(np.median(a)), 1), "p95": round(float(np.percentile(a, 95)), 1)}


def bootstrap_mean_ci(values: list[float], n_boot: int = 4000) -> tuple[float, float] | None:
    if len(values) < 2:
        return None
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    a = np.asarray(values, dtype=float)
    means = rng.choice(a, size=(n_boot, a.size), replace=True).mean(axis=1)
    return (round(float(np.percentile(means, 2.5)), 1), round(float(np.percentile(means, 97.5)), 1))


def _rate(k: int, n: int) -> dict:
    lo, hi = wilson_interval(k, n)
    return {
        "k": k,
        "n": n,
        "rate": round(k / n, 4) if n else None,
        "ci95": [round(lo, 3), round(hi, 3)],
    }


def summarise_runs(runs: list[dict]) -> dict:
    n = len(runs)
    if n == 0:
        return {"runs": 0}
    tool_calls = sum(r["tool_calls"] for r in runs)
    tool_errors = sum(r["tool_errors"] for r in runs)
    return {
        "runs": n,
        "completion_rate": round(sum(r["status"] == "completed" for r in runs) / n, 4),
        "recommendation_rate": round(
            sum(r["recommendation"] == "awaiting_approval" for r in runs) / n, 4
        ),
        "no_safe_action_rate": round(
            sum(r["recommendation"] == "no_safe_action_found" for r in runs) / n, 4
        ),
        "tool_calls": tool_calls,
        "tool_success_rate": round(1 - tool_errors / tool_calls, 4) if tool_calls else None,
        "invalid_actions": sum(r["invalid_actions"] for r in runs),
        "verifier_rejections": sum(r["rejections"] for r in runs),
        "runs_with_rejection": sum(r["rejections"] > 0 for r in runs),
        "latency_ms": _stats([r["latency_ms"] for r in runs]),
        "llm_calls": sum(r.get("llm_calls", 0) for r in runs),
        "input_tokens": sum(r.get("input_tokens", 0) for r in runs),
        "cached_input_tokens": sum(r.get("cached_input_tokens", 0) for r in runs),
        "output_tokens": sum(r.get("output_tokens", 0) for r in runs),
        "estimated_cost_usd": round(sum(r.get("estimated_cost_usd", 0.0) for r in runs), 6),
        "hallucinated_evidence_ids": sum(r.get("hallucinated_evidence_ids", 0) for r in runs),
        "fallbacks": sum(r.get("selected_by") == "optimizer_fallback" for r in runs),
        **_regret_summary(runs),
    }


def _regret_summary(runs: list[dict]) -> dict:
    audited = [r for r in runs if r.get("audit")]
    if not audited:
        return {}
    regrets = [r["audit"]["regret_vs_planner"] for r in audited]
    unsafe = sum(r["audit"]["agent_failure_incidence"] > 0 for r in audited)
    healthy = [r for r in runs if r["case"].startswith(ScenarioId.HEALTHY.value)]
    false_alarms = sum(r["recommendation"] == "awaiting_approval" for r in healthy)
    out = {
        "audited_runs": len(regrets),
        "mean_regret_vs_planner_usd": round(float(np.mean(regrets)), 1),
        "mean_regret_ci95": bootstrap_mean_ci(regrets),
        "runs_worse_than_planner": sum(x > 0 for x in regrets),
        "runs_better_than_planner": sum(x < 0 for x in regrets),
        "unsafe_choice": _rate(unsafe, len(audited)),
    }
    if healthy:
        out["healthy_false_intervention"] = _rate(false_alarms, len(healthy))
    return out


def deterministic_agent_metrics(intervention_eval: dict) -> dict:
    runs = [
        run
        for ep in intervention_eval["episodes"]
        if ep["policy"].startswith("foresight")
        for run in ep["agent_runs"]
    ]
    return {
        "provider": "deterministic-planner",
        "source": "agent runs triggered inside the closed-loop intervention evaluation",
        **summarise_runs(runs),
    }


def _audit_regret(snap: AgentSnapshot, agent_action: dict | None, planner_action: dict | None):
    """Score both chosen actions in one fresh comparison with shared seeds.

    Regret is the agent branch objective minus the planner branch objective (USD; positive
    means the agent's choice is worse under the simulator's objective)."""
    if agent_action is None or planner_action is None:
        return None
    actions = [ACTION_ADAPTER.validate_python(agent_action)]
    if planner_action != agent_action:
        actions.append(ACTION_ADAPTER.validate_python(planner_action))
    comp = compare_futures(
        actions,
        horizon_min=180.0,
        n_members=AUDIT_MEMBERS,
        base_seed=AUDIT_SEED,
        state_source="estimated",
        estimate=estimate_state(snap.samples, snap.actuators),
    )
    agent_branch = comp.branch_for_action(actions[0])
    planner_branch = comp.branch_for_action(actions[-1])
    return {
        "agent_objective": round(agent_branch.objective, 1),
        "planner_objective": round(planner_branch.objective, 1),
        "regret_vs_planner": round(agent_branch.objective - planner_branch.objective, 1),
        "agent_failure_incidence": round(agent_branch.failure_incidence, 3),
    }


@dataclass
class EvalCase:
    scenario: ScenarioId
    label: str
    t_s: float
    samples: list
    assessment: RiskAssessment
    planner_action: dict | None
    planner_label: str | None

    def snapshot(self, tag: str) -> AgentSnapshot:
        return AgentSnapshot(
            f"eval-{self.label}-{tag}", self.t_s, self.samples, ActuatorSettings(), self.assessment
        )


async def prepare_cases(bundle: RiskBundle, settings: Settings) -> list[EvalCase]:
    """Telemetry snapshots and the deterministic planner's choice for every LIVE_CASES entry."""
    cases = []
    for scenario, seed, minute in LIVE_CASES:
        stream = TelemetryStream(canonical_episode(scenario, seed=seed))
        engine = RiskEngine(bundle)
        assessment = None
        for _ in range(minute):
            stream.advance(60)
            assessment = engine.assess(list(stream.window))
        case = EvalCase(
            scenario=scenario,
            label=f"{scenario.value}@{minute}min/s{seed}",
            t_s=stream.t_s,
            samples=list(stream.window)[-720:],
            assessment=assessment,  # type: ignore[arg-type]
            planner_action=None,
            planner_label=None,
        )
        planner = (
            await AgentOrchestrator(case.snapshot("planner"), settings, llm=None).run()
        ).recommendation
        case.planner_action = planner.action if planner else None
        case.planner_label = planner.action_label if planner else None
        cases.append(case)
    return cases


async def _one_run(
    arm: Arm, client: ModelClient, case: EvalCase, rep: int, settings: Settings
) -> dict:
    snap = case.snapshot(f"{arm.key}-{rep}")
    trace = await AgentOrchestrator(snap, settings, llm=client).run()
    rec = trace.recommendation
    audit = await asyncio.to_thread(
        _audit_regret, snap, rec.action if rec else None, case.planner_action
    )
    return {
        "arm": arm.key,
        "provider": arm.provider,
        "effort": arm.effort,
        "model": client.model,
        "case": case.label,
        "repeat": rep,
        "status": trace.status,
        "latency_ms": round(trace.latency_ms or 0.0, 1),
        "tool_calls": trace.usage.tool_calls,
        "tool_errors": trace.usage.tool_errors,
        "invalid_actions": trace.usage.invalid_actions,
        "rejections": len(trace.rejected),
        "rejected": [r.action_label for r in trace.rejected],
        "recommendation": rec.status if rec else None,
        "action": rec.action_label if rec else None,
        "selected_by": rec.selected_by if rec else None,
        "llm_calls": trace.usage.llm_calls,
        "input_tokens": trace.usage.input_tokens,
        "cached_input_tokens": trace.usage.cached_input_tokens,
        "output_tokens": trace.usage.output_tokens,
        "estimated_cost_usd": trace.usage.estimated_cost_usd,
        "hallucinated_evidence_ids": trace.usage.hallucinated_evidence_ids,
        "planner_action": case.planner_label,
        "audit": audit,
        "error": trace.error,
        "provider_trace": trace.provider,
    }


async def run_arms(
    bundle: RiskBundle,
    settings: Settings,
    arms: list[Arm],
    repeats: int,
    concurrency_per_provider: int = 3,
    on_progress=None,
) -> list[dict]:
    cases = await prepare_cases(bundle, settings)
    clients: dict[str, ModelClient] = {}
    try:
        for arm in arms:
            if arm.provider not in clients:
                clients[arm.provider] = ModelClient(settings, provider=arm.provider)
        sems = {p: asyncio.Semaphore(concurrency_per_provider) for p in clients}
        total = len(arms) * len(cases) * repeats
        done = 0

        async def task(arm: Arm, case: EvalCase, rep: int) -> dict:
            nonlocal done
            async with sems[arm.provider]:
                result = await _one_run(
                    arm, clients[arm.provider].with_effort(arm.effort), case, rep, settings
                )
            done += 1
            if on_progress:
                on_progress(done, total, result)
            return result

        jobs = [task(a, c, r) for r in range(repeats) for c in cases for a in arms]
        return list(await asyncio.gather(*jobs))
    finally:
        for c in clients.values():
            await c.aclose()


def live_agent_metrics(
    bundle: RiskBundle,
    settings: Settings,
    run: bool,
    arms: list[Arm] | None = None,
    repeats: int = 2,
    concurrency_per_provider: int = 3,
    on_progress=None,
) -> dict:
    arms = arms or [Arm(settings.llm_provider, settings.reasoning_effort)]
    missing = sorted({a.provider for a in arms if not settings.provider(a.provider).configured})
    if missing:
        return {"status": "not_run", "reason": f"No API key configured for: {', '.join(missing)}."}
    if not run:
        return {
            "status": "not_run",
            "reason": "Live agent evaluation not requested (--live-agent).",
        }
    for a in arms:
        efforts = settings.provider(a.provider).efforts
        if a.effort not in efforts:
            return {
                "status": "not_run",
                "reason": f"Effort {a.effort!r} not supported by {a.provider}; use {list(efforts)}",
            }
    runs = asyncio.run(
        run_arms(bundle, settings, arms, repeats, concurrency_per_provider, on_progress)
    )
    by_arm = []
    for a in arms:
        arm_runs = [r for r in runs if r["arm"] == a.key]
        cfg = settings.provider(a.provider)
        by_arm.append(
            {
                "arm": a.key,
                "provider": a.provider,
                "provider_label": cfg.label,
                "model": cfg.model,
                "effort": a.effort,
                **summarise_runs(arm_runs),
            }
        )
    return {
        "status": "run",
        "cases": [r[0].value + f"@{r[2]}min/s{r[1]}" for r in LIVE_CASES],
        "repeats": repeats,
        "audit": {"seed": AUDIT_SEED, "members": AUDIT_MEMBERS, "horizon_min": 180.0},
        "arms": by_arm,
        **summarise_runs(runs),
        "runs_detail": runs,
    }
