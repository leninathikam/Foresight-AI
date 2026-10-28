"""Agent tools. Each tool validates its arguments and runs deterministic code on a frozen
snapshot of the session, so every number the agent sees is traceable to a computation."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np
from pydantic import ValidationError

from foresight.branching import (
    ACTION_ADAPTER,
    ActuatorSettings,
    BranchOutcome,
    FutureComparison,
    StateEstimate,
    compare_futures,
    estimate_state,
)
from foresight.prediction.schemas import EvidenceItem, RiskAssessment
from foresight.simulation import Action, MotorTwin
from foresight.telemetry import CHANNELS, TelemetrySample
from foresight.verification import Proposal, VerificationResult, verify_independently


class ToolError(ValueError):
    """Raised for invalid tool arguments; reported back to the model, never crashes the run."""


@dataclass
class AgentSnapshot:
    session_id: str
    t_s: float
    samples: list[TelemetrySample]
    actuators: ActuatorSettings
    assessment: RiskAssessment
    oracle_twin: MotorTwin | None = None  # never exposed to the model
    # "oracle" plans from the hidden true state; only used by the evaluation upper bound.
    planning_state_source: Literal["estimated", "oracle"] = "estimated"


def action_from_flat(d: Any) -> Action:
    """Convert the model's flat action object into a typed Action."""
    if not isinstance(d, dict) or "type" not in d:
        raise ToolError("action must be an object with a 'type' field")
    kind = d["type"]
    needed = {
        "reduce_load": "fraction",
        "reduce_speed": "fraction",
        "increase_cooling": "boost",
        "schedule_inspection": "delay_minutes",
    }.get(kind)
    payload: dict[str, Any] = {"type": kind}
    if needed:
        if d.get(needed) is None:
            raise ToolError(f"action '{kind}' requires numeric '{needed}'")
        payload[needed] = d[needed]
    try:
        return ACTION_ADAPTER.validate_python(payload)
    except ValidationError as exc:
        raise ToolError(f"invalid action {d}: {exc.errors()[0]['msg']}") from exc


def branch_summary(comparison: FutureComparison, b: BranchOutcome) -> dict:
    return {
        "evidence_id": f"sim:{comparison.id}:{b.branch_id}",
        "action": b.label,
        "failure_incidence": round(b.failure_incidence, 3),
        "failure_incidence_ci95": [round(x, 3) for x in b.failure_incidence_ci95],
        "failure_modes": b.failure_modes,
        "median_time_to_failure_min": None
        if b.median_time_to_failure_min is None
        else round(b.median_time_to_failure_min, 1),
        "peak_temperature_p90_c": round(b.peak_temperature_p90_c, 1),
        "peak_vibration_p90_mm_s": round(b.peak_vibration_p90_mm_s, 2),
        "max_running_load": round(b.max_running_load, 3),
        "downtime_mean_h": round(b.downtime_mean_h, 2),
        "expected_cost_usd": round(b.cost_mean, 0),
        "objective": round(b.objective, 0),
        "end_in_alarm_zone_fraction": round(b.end_alarm_fraction, 3),
    }


@dataclass
class ToolExecutor:
    snapshot: AgentSnapshot
    horizon_min: float = 180.0
    n_members: int = 8
    comparisons: dict[str, FutureComparison] = field(default_factory=dict)
    verifications: list[VerificationResult] = field(default_factory=list)
    estimate: StateEstimate | None = None

    def __post_init__(self) -> None:
        self.evidence: dict[str, EvidenceItem] = {
            e.id: e for e in self.snapshot.assessment.evidence
        }

    # ------------------------------------------------------------------ helpers
    def known_evidence_ids(self) -> set[str]:
        return set(self.evidence)

    def comparison_for(self, action: Action) -> FutureComparison | None:
        for comp in reversed(list(self.comparisons.values())):
            if comp.branch_for_action(action) is not None:
                return comp
        return None

    def _register_comparison(self, comp: FutureComparison) -> None:
        self.comparisons[comp.id] = comp
        for b in comp.branches:
            eid = f"sim:{comp.id}:{b.branch_id}"
            self.evidence[eid] = EvidenceItem(
                id=eid,
                kind="simulation_estimate",
                signal=f"branch:{b.label}",
                value=round(b.failure_incidence, 4),
                description=(
                    f"{b.label}: failure incidence {b.failure_incidence:.0%} over {comp.horizon_min:.0f} min, "
                    f"p90 peak {b.peak_temperature_p90_c:.1f} °C / {b.peak_vibration_p90_mm_s:.2f} mm/s"
                ),
            )

    # ------------------------------------------------------------------ tools
    async def call(self, name: str, args: dict) -> tuple[str, dict]:
        handler = getattr(self, f"tool_{name}", None)
        if handler is None:
            raise ToolError(f"unknown tool '{name}'")
        return await handler(**args) if asyncio.iscoroutinefunction(handler) else handler(**args)

    def tool_get_machine_state(self) -> tuple[str, dict]:
        last = self.snapshot.samples[-1]
        a = self.snapshot.actuators
        result = {
            "sim_time_min": round(last.t_s / 60.0, 1),
            "running": last.running,
            "latest": {k: (None if v is None else round(v, 3)) for k, v in last.values.items()},
            "quality": last.quality,
            "drive_commands": {
                "load_multiplier": round(a.load_multiplier, 3),
                "speed_setpoint": round(a.speed_setpoint, 3),
                "aux_cooling_boost": round(a.aux_boost, 3),
            },
            "note": "Observed values only; bearing health and cooling efficiency are not directly measured.",
        }
        v = last.values

        def fmt(key: str, digits: int) -> str:
            x = v.get(key)
            return "n/a" if x is None else f"{x:.{digits}f}"

        return (
            f"T={fmt('temperature_c', 1)} °C, vib={fmt('vibration_mm_s', 2)} mm/s, "
            f"load={fmt('load_pct', 1)} %",
            result,
        )

    def tool_get_sensor_history(self, channel: str, minutes: float = 30.0) -> tuple[str, dict]:
        if channel not in CHANNELS:
            raise ToolError(f"channel must be one of {list(CHANNELS)}")
        minutes = float(np.clip(minutes, 5.0, 120.0))
        t_end = self.snapshot.samples[-1].t_s
        window = [s for s in self.snapshot.samples if s.t_s > t_end - minutes * 60.0]
        t = np.array([s.t_s for s in window]) / 60.0
        y = np.array(
            [np.nan if s.values[channel] is None else s.values[channel] for s in window],
            dtype=float,
        )
        valid = np.isfinite(y)
        if valid.sum() < 3:
            return (
                "insufficient valid data",
                {"channel": channel, "valid_points": int(valid.sum())},
            )
        slope = float(np.polyfit(t[valid], y[valid], 1)[0])
        idx = np.linspace(0, len(window) - 1, num=min(24, len(window))).astype(int)
        series = [
            {
                "t_min": round(float(t[i]), 1),
                "value": None if not np.isfinite(y[i]) else round(float(y[i]), 3),
            }
            for i in idx
        ]
        result = {
            "channel": channel,
            "minutes": minutes,
            "min": round(float(np.nanmin(y)), 3),
            "max": round(float(np.nanmax(y)), 3),
            "mean": round(float(np.nanmean(y)), 3),
            "slope_per_min": round(slope, 5),
            "missing_fraction": round(float(1 - valid.mean()), 3),
            "series": series,
        }
        return (f"{channel}: {result['min']}–{result['max']}, slope {slope:+.4f}/min", result)

    def tool_analyze_anomalies(self) -> tuple[str, dict]:
        a = self.snapshot.assessment
        top = [e.model_dump() for e in a.evidence if e.kind == "observed"][:6]
        result = {
            "anomaly": a.anomaly.model_dump() if a.anomaly else None,
            "change_points": [c.model_dump() for c in a.change_points],
            "most_deviant_features": top,
        }
        flag = "anomalous" if a.anomaly and a.anomaly.is_anomalous else "normal"
        detected = [c.signal for c in a.change_points if c.detected]
        return (f"isolation forest: {flag}; change points: {detected or 'none'}", result)

    def tool_predict_failure_risk(self) -> tuple[str, dict]:
        a = self.snapshot.assessment
        result = {
            "horizons": [h.model_dump() for h in a.horizons],
            "fault_class_probabilities": [d.model_dump() for d in a.diagnosis],
            "heuristic_minutes_to_temp_limit": a.heuristic_minutes_to_temp_limit,
            "evidence_ids": [e.id for e in a.evidence if e.kind == "ml_prediction"],
        }
        risk = ", ".join(f"{h.horizon_min}m={h.probability:.2f}" for h in a.horizons)
        return (f"risk {risk}; top class {a.diagnosis[0].label if a.diagnosis else '?'}", result)

    def tool_inspect_visual_evidence(self, component: str = "motor") -> tuple[str, dict]:
        return (
            "unavailable",
            {
                "status": "unavailable",
                "component": component,
                "reason": "No camera or thermal-imaging source is configured for this simulated asset. "
                "Visual evidence cannot be used in this diagnosis.",
            },
        )

    def _ensure_estimate(self) -> StateEstimate:
        if self.estimate is None:
            try:
                self.estimate = estimate_state(self.snapshot.samples, self.snapshot.actuators)
            except ValueError as exc:
                raise ToolError(str(exc)) from exc
        return self.estimate

    async def tool_compare_futures(
        self, actions: list, horizon_min: float | None = None
    ) -> tuple[str, dict]:
        if not isinstance(actions, list) or not 1 <= len(actions) <= 5:
            raise ToolError("actions must be a list of 1-5 action objects")
        typed = [action_from_flat(a) for a in actions]
        horizon = float(np.clip(horizon_min or self.horizon_min, 60.0, 240.0))
        comp = await self.run_comparison(typed, horizon)
        branches = [branch_summary(comp, b) for b in comp.branches]
        best = next(b for b in comp.branches if b.branch_id == comp.ranking[0])
        result = {
            "comparison_id": comp.id,
            "horizon_min": horizon,
            "members": comp.n_members,
            "state_source": comp.state_source,
            "state_estimate": comp.estimate.model_dump(exclude={"actuators"})
            if comp.estimate
            else None,
            "objective": comp.objective_definition,
            "branches": branches,
            "ranking_by_objective": comp.ranking,
            "note": "Simulation estimates under documented twin assumptions; not measurements.",
        }
        return (f"{len(branches)} branches; lowest objective: {best.label}", result)

    async def run_comparison(self, actions: list[Action], horizon_min: float) -> FutureComparison:
        est = self._ensure_estimate()
        oracle = self.snapshot.planning_state_source == "oracle"
        if oracle and self.snapshot.oracle_twin is None:
            raise ToolError("oracle planning requested without a twin")
        comp = await asyncio.to_thread(
            compare_futures,
            actions,
            horizon_min=horizon_min,
            n_members=self.n_members,
            base_seed=len(self.comparisons),
            state_source="oracle" if oracle else "estimated",
            estimate=est,
            oracle_twin=self.snapshot.oracle_twin if oracle else None,
        )
        self._register_comparison(comp)
        return comp

    async def run_verification(self, proposal: Proposal) -> VerificationResult:
        comp = self.comparison_for(proposal.action)
        oracle = self.snapshot.oracle_twin.clone() if self.snapshot.oracle_twin else None
        result = await asyncio.to_thread(
            verify_independently,
            proposal,
            comp,
            self.snapshot.assessment,
            now_s=self.snapshot.t_s,
            known_evidence_ids=self.known_evidence_ids(),
            oracle_twin=oracle,
        )
        self.verifications.append(result)
        return result

    async def tool_verify_intervention(
        self, action: dict, claimed_failure_mode: str = "unknown"
    ) -> tuple[str, dict]:
        typed = action_from_flat(action)
        res = await self.run_verification(
            Proposal(action=typed, claimed_failure_mode=claimed_failure_mode, source="agent")
        )
        return (res.summary, res.model_dump())
