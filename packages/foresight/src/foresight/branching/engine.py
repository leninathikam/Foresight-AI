"""Future Branching Engine: counterfactual simulation of interventions from one shared state.

For every branch we clone the *same* initial state, apply that branch's intervention, and
simulate the same horizon for an ensemble of members. Member ``j`` uses the same disturbance
seed and the same sampled parameter perturbation in every branch (common random numbers), so
differences between branches are attributable to the intervention rather than to noise.

Outcomes are *simulation estimates* under the twin's assumptions, not proven causal effects.
"""

from __future__ import annotations

import math
import time
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Literal

import numpy as np
from pydantic import BaseModel, Field, TypeAdapter

from foresight.branching.estimation import StateEstimate
from foresight.simulation import (
    DEFAULT_ECONOMICS,
    DEFAULT_MOTOR,
    STEP_S,
    Action,
    ContinueOperation,
    EconomicParameters,
    EpisodeConfig,
    FaultConfig,
    MotorState,
    MotorTwin,
    ScenarioId,
    describe_action,
)

StateSource = Literal["estimated", "oracle"]
ACTION_ADAPTER: TypeAdapter[Action] = TypeAdapter(Action)
TRAJECTORY_EVERY_S = 60.0
DETECTABLE_DAMAGE = 0.15  # below this, vibration-inferred damage is within sensor-noise bias
PLANNING_SEED_OFFSET = 900_000


class CostBreakdown(BaseModel):
    lost_production: float = 0.0
    failure_repair: float = 0.0
    failure_downtime: float = 0.0
    intervention: float = 0.0
    deferred_maintenance: float = 0.0
    terminal_risk_penalty: float = 0.0

    @property
    def total(self) -> float:
        return (
            self.lost_production
            + self.failure_repair
            + self.failure_downtime
            + self.intervention
            + self.deferred_maintenance
            + self.terminal_risk_penalty
        )


class MemberOutcome(BaseModel):
    seed: int
    failed: bool
    failure_mode: str | None
    failure_time_min: float | None
    peak_temperature_c: float
    peak_vibration_mm_s: float
    max_running_load: float
    downtime_h: float
    end_in_alarm_zone: bool
    cost: CostBreakdown


class Band(BaseModel):
    t_min: list[float]
    p10: list[float]
    p50: list[float]
    p90: list[float]


class BranchOutcome(BaseModel):
    branch_id: str
    label: str
    action: dict
    n_members: int
    failure_incidence: float
    failure_incidence_ci95: tuple[float, float]
    failure_modes: dict[str, int]
    median_time_to_failure_min: float | None
    peak_temperature_mean_c: float
    peak_temperature_p90_c: float
    peak_vibration_mean_mm_s: float
    peak_vibration_p90_mm_s: float
    max_running_load: float
    downtime_mean_h: float
    cost_mean: float
    cost_breakdown_mean: CostBreakdown
    objective: float
    end_alarm_fraction: float
    temperature_band: Band
    vibration_band: Band
    delta_vs_baseline: dict[str, float] = Field(default_factory=dict)
    members: list[MemberOutcome] = Field(default_factory=list, exclude=True)


class FutureComparison(BaseModel):
    id: str
    created_at: str
    t0_s: float
    horizon_min: float
    n_members: int
    state_source: StateSource
    estimate: StateEstimate | None
    baseline_branch_id: str
    branches: list[BranchOutcome]
    ranking: list[str] = Field(description="Branch ids sorted by objective (lower is better)")
    seeds: list[int]
    objective_definition: str
    assumptions: list[str]
    compute_ms: float

    def branch_for_action(self, action: Action) -> BranchOutcome | None:
        target = ACTION_ADAPTER.dump_python(action, mode="json")
        for b in self.branches:
            if _actions_equal(b.action, target):
                return b
        return None


def _actions_equal(a: dict, b: dict) -> bool:
    if a.get("type") != b.get("type"):
        return False
    for k in set(a) | set(b):
        va, vb = a.get(k), b.get(k)
        if isinstance(va, float | int) and isinstance(vb, float | int):
            if not math.isclose(float(va), float(vb), abs_tol=1e-6):
                return False
        elif va != vb:
            return False
    return True


OBJECTIVE_DEFINITION = (
    "Expected cost over the horizon (lost production + unplanned failure repair + failure downtime "
    "+ intervention cost) + deferred maintenance (the inspection/repair still owed when a fault is "
    "left unresolved at the horizon, e.g. after a shutdown) + terminal risk penalty (repair cost x "
    "fraction of ensemble members that end the horizon running inside an alarm zone: winding > "
    "130 °C or vibration > 4.5 mm/s). Lower is better. Safety limits are enforced separately by "
    "the verifier, not traded off here."
)

UNRESOLVED_DAMAGE = 0.2
UNRESOLVED_COOLING = 0.75

ASSUMPTIONS = [
    "Lumped single-node thermal model; no separate stator/rotor/bearing temperatures.",
    "Constant-torque conveyor load: reducing speed does not reduce torque.",
    "Shaft-fan airflow is proportional to speed; the auxiliary blower adds up to 40 % airflow.",
    "Bearing damage grows exponentially with load^3 x speed after a defect initiates.",
    "Inspection cleans cooling paths, clears conveyor build-up, and replaces a bearing if damage > 20 %.",
    "Economic values are illustrative (USD) and documented in simulation/params.py.",
    "Estimated-state branches use telemetry-fitted parameters with sampled uncertainty; they are "
    "simulation estimates, not causal proof.",
]


def wilson_interval(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    phat = k / n
    denom = 1 + z**2 / n
    centre = (phat + z**2 / (2 * n)) / denom
    half = z * math.sqrt(phat * (1 - phat) / n + z**2 / (4 * n**2)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


# ---------------------------------------------------------------------- twin construction


def planning_twin_from_estimate(
    est: StateEstimate, horizon_s: float, seed: int, perturb: np.random.Generator | None
) -> MotorTwin:
    """Build a planning twin from estimated state. ``perturb`` samples parameter uncertainty."""

    def jitter(value: float, std: float, lo: float, hi: float) -> float:
        if perturb is None:
            return value
        return float(np.clip(value + std * perturb.standard_normal(), lo, hi))

    eta = jitter(est.cooling_efficiency, est.cooling_efficiency_std, 0.05, 1.0)
    fouling_rate = max(0.0, -est.cooling_trend_per_h)
    fouling_rate = jitter(fouling_rate, 0.25 * fouling_rate + 0.01, 0.0, 2.0)
    damage = jitter(est.bearing_damage, est.bearing_damage_std, 0.0, 0.95)
    growth = jitter(est.bearing_growth_per_h, 0.25 * est.bearing_growth_per_h, 0.0, 5.0)
    load_trend = jitter(est.load_trend_per_h, 0.2 * abs(est.load_trend_per_h) + 0.005, -1.0, 2.0)

    t0 = est.t_s
    fault = FaultConfig(
        cooling_fouling_onset_s=t0 if fouling_rate > 0.02 else None,
        cooling_fouling_rate_per_h=fouling_rate,
        cooling_floor=0.1,
        bearing_defect_onset_s=t0 if damage > DETECTABLE_DAMAGE and growth > 0 else None,
        bearing_initial_damage=damage,
        bearing_growth_per_h=growth,
    )
    base_load = est.process_load
    if load_trend > 0.03:
        # Continue the observed ramp. The ramp's start is placed in the past so that the build-up
        # at t0 equals (current - baseline); inspection removes the build-up.
        horizon_h = horizon_s / 3600.0
        base_load = est.baseline_process_load
        built_up = max(0.0, est.process_load - base_load)
        target = min(1.6, est.process_load + load_trend * horizon_h)
        if target - base_load > 1e-3:
            ramp_h = (target - base_load) / load_trend
            fault.overload_onset_s = t0 - built_up / load_trend * 3600.0
            fault.overload_ramp_h = ramp_h
            fault.overload_target_load = target

    config = EpisodeConfig(
        scenario=ScenarioId.HEALTHY,
        seed=seed,
        duration_s=t0 + horizon_s,
        base_load=base_load,
        speed_setpoint=est.actuators.speed_setpoint,
        ambient_c=est.ambient_c,
        fault=fault,
    )
    state = MotorState(
        t_s=t0,
        temperature_c=est.temperature_c,
        ambient_c=est.ambient_c,
        bearing_damage=damage,
        cooling_efficiency=eta,
        load_multiplier=est.actuators.load_multiplier,
        speed_setpoint=est.actuators.speed_setpoint,
        aux_boost=est.actuators.aux_boost,
        bearing_defect_active=fault.bearing_defect_onset_s is not None,
        cooling_fouling_active=fault.cooling_fouling_onset_s is not None,
    )
    return MotorTwin(config, state=state)


# ---------------------------------------------------------------------- simulation


def _simulate_member(
    twin: MotorTwin,
    action: Action,
    horizon_s: float,
    econ: EconomicParameters,
    seed: int,
) -> tuple[MemberOutcome, list[float], list[float]]:
    t0 = twin.state.t_s
    start_production = twin.state.production_equiv_s
    start_inspections = twin.state.inspections
    start_replacements = twin.state.bearing_replacements
    start_aux = twin.state.aux_cooling_s
    start_downtime = twin.state.downtime_s
    twin.apply_action(action)

    n_steps = round(horizon_s / STEP_S)
    every = max(1, round(TRAJECTORY_EVERY_S / STEP_S))
    temps: list[float] = []
    vibs: list[float] = []
    peak_t, peak_v, max_load = twin.state.temperature_c, 0.0, 0.0
    for i in range(1, n_steps + 1):
        reading, _ = twin.step()
        peak_t = max(peak_t, twin.state.temperature_c)
        out = twin.last_outputs
        if reading.running:
            peak_v = max(peak_v, out.vibration_mm_s)
            max_load = max(max_load, out.load_fraction)
        if i % every == 0:
            temps.append(twin.state.temperature_c)
            vibs.append(out.vibration_mm_s if reading.running else 0.0)

    s = twin.state
    horizon_h = horizon_s / 3600.0
    produced_h = (s.production_equiv_s - start_production) / 3600.0
    cost = CostBreakdown(
        lost_production=econ.production_margin_per_hour * max(0.0, horizon_h - produced_h)
    )
    failed = s.failed and s.failure_time_s is not None and s.failure_time_s > t0
    failure_time_min = (s.failure_time_s - t0) / 60.0 if failed else None
    if failed:
        cost.failure_repair = econ.unplanned_failure_repair_cost
        remaining_h = horizon_h - failure_time_min / 60.0
        cost.failure_downtime = econ.production_margin_per_hour * max(
            0.0, econ.unplanned_failure_downtime_h - remaining_h
        )
    cost.intervention = (
        (s.inspections - start_inspections) * econ.inspection_cost
        + (s.bearing_replacements - start_replacements) * econ.bearing_replacement_cost
        + (s.aux_cooling_s - start_aux) / 3600.0 * econ.aux_cooling_cost_per_hour
        + (econ.restart_cost if s.shutdown else 0.0)
    )
    if not failed:
        unresolved = (
            s.bearing_damage > UNRESOLVED_DAMAGE
            or s.cooling_efficiency < UNRESOLVED_COOLING
            or s.overload_extra > 0.05
        )
        if unresolved:
            cost.deferred_maintenance = (
                econ.inspection_cost + econ.inspection_downtime_h * econ.production_margin_per_hour
            )
            if s.bearing_damage > UNRESOLVED_DAMAGE:
                cost.deferred_maintenance += (
                    econ.bearing_replacement_cost
                    + econ.bearing_replacement_extra_downtime_h * econ.production_margin_per_hour
                )
    end_alarm = False
    if s.running:
        out = twin.true_outputs()
        end_alarm = (
            s.temperature_c > DEFAULT_MOTOR.temperature_warning_c
            or out.vibration_mm_s > DEFAULT_MOTOR.vibration_alarm_mm_s
        )
    cost.terminal_risk_penalty = econ.unplanned_failure_repair_cost if end_alarm else 0.0
    member = MemberOutcome(
        seed=seed,
        failed=failed,
        failure_mode=s.failure_mode if failed else None,
        failure_time_min=failure_time_min,
        peak_temperature_c=peak_t,
        peak_vibration_mm_s=peak_v,
        max_running_load=max_load,
        downtime_h=(s.downtime_s - start_downtime) / 3600.0,
        end_in_alarm_zone=end_alarm,
        cost=cost,
    )
    return member, temps, vibs


def _band(series: list[list[float]], every_s: float) -> Band:
    arr = np.array(series, dtype=float)
    t_min = [round((i + 1) * every_s / 60.0, 2) for i in range(arr.shape[1])]
    p10, p50, p90 = np.percentile(arr, [10, 50, 90], axis=0)
    return Band(
        t_min=t_min,
        p10=[round(float(x), 3) for x in p10],
        p50=[round(float(x), 3) for x in p50],
        p90=[round(float(x), 3) for x in p90],
    )


def _summarise(branch_id: str, action: Action, members, temps, vibs) -> BranchOutcome:
    n = len(members)
    k = sum(m.failed for m in members)
    modes: dict[str, int] = {}
    for m in members:
        if m.failure_mode:
            modes[m.failure_mode] = modes.get(m.failure_mode, 0) + 1
    ttfs = [m.failure_time_min for m in members if m.failure_time_min is not None]
    peak_t = np.array([m.peak_temperature_c for m in members])
    peak_v = np.array([m.peak_vibration_mm_s for m in members])
    mean_cost = CostBreakdown(
        **{
            f: float(np.mean([getattr(m.cost, f) for m in members]))
            for f in CostBreakdown.model_fields
        }
    )
    return BranchOutcome(
        branch_id=branch_id,
        label=describe_action(action),
        action=ACTION_ADAPTER.dump_python(action, mode="json"),
        n_members=n,
        failure_incidence=k / n,
        failure_incidence_ci95=wilson_interval(k, n),
        failure_modes=modes,
        median_time_to_failure_min=float(np.median(ttfs)) if ttfs else None,
        peak_temperature_mean_c=float(peak_t.mean()),
        peak_temperature_p90_c=float(np.percentile(peak_t, 90)),
        peak_vibration_mean_mm_s=float(peak_v.mean()),
        peak_vibration_p90_mm_s=float(np.percentile(peak_v, 90)),
        max_running_load=float(max(m.max_running_load for m in members)),
        downtime_mean_h=float(np.mean([m.downtime_h for m in members])),
        cost_mean=mean_cost.total - mean_cost.terminal_risk_penalty,
        cost_breakdown_mean=mean_cost,
        objective=mean_cost.total,
        end_alarm_fraction=float(np.mean([m.end_in_alarm_zone for m in members])),
        temperature_band=_band(temps, TRAJECTORY_EVERY_S),
        vibration_band=_band(vibs, TRAJECTORY_EVERY_S),
        members=members,
    )


def compare_futures(
    actions: Sequence[Action],
    *,
    horizon_min: float = 180.0,
    n_members: int = 8,
    base_seed: int = 0,
    state_source: StateSource = "estimated",
    estimate: StateEstimate | None = None,
    oracle_twin: MotorTwin | None = None,
    economics: EconomicParameters = DEFAULT_ECONOMICS,
) -> FutureComparison:
    """Simulate each action (plus a no-action baseline) from the same initial state."""
    start = time.perf_counter()
    if state_source == "estimated" and estimate is None:
        raise ValueError("estimated branching needs a StateEstimate")
    if state_source == "oracle" and oracle_twin is None:
        raise ValueError("oracle branching needs the live twin")

    all_actions: list[Action] = [ContinueOperation()]
    for a in actions:
        if not any(
            _actions_equal(
                ACTION_ADAPTER.dump_python(a, mode="json"),
                ACTION_ADAPTER.dump_python(b, mode="json"),
            )
            for b in all_actions
        ):
            all_actions.append(a)

    horizon_s = horizon_min * 60.0
    seeds = [PLANNING_SEED_OFFSET + base_seed * 1000 + j for j in range(n_members)]

    # Build each member's initial twin once; every branch clones it (identical start + RNG).
    initial: list[MotorTwin] = []
    for seed in seeds:
        if state_source == "oracle":
            initial.append(oracle_twin.clone(reseed=seed))  # type: ignore[union-attr]
        else:
            perturb = np.random.default_rng(seed)
            initial.append(planning_twin_from_estimate(estimate, horizon_s, seed, perturb))  # type: ignore[arg-type]
    t0 = initial[0].state.t_s

    outcomes: list[BranchOutcome] = []
    for idx, action in enumerate(all_actions):
        members, temps, vibs = [], [], []
        for seed, twin0 in zip(seeds, initial, strict=True):
            member, ts, vs = _simulate_member(twin0.clone(), action, horizon_s, economics, seed)
            members.append(member)
            temps.append(ts)
            vibs.append(vs)
        outcomes.append(
            _summarise("baseline" if idx == 0 else f"b{idx}", action, members, temps, vibs)
        )

    base = outcomes[0]
    for o in outcomes:
        o.delta_vs_baseline = {
            "failure_incidence": o.failure_incidence - base.failure_incidence,
            "objective": o.objective - base.objective,
            "peak_temperature_c": o.peak_temperature_mean_c - base.peak_temperature_mean_c,
            "peak_vibration_mm_s": o.peak_vibration_mean_mm_s - base.peak_vibration_mean_mm_s,
            "downtime_h": o.downtime_mean_h - base.downtime_mean_h,
        }
    ranking = [o.branch_id for o in sorted(outcomes, key=lambda o: o.objective)]
    return FutureComparison(
        id=f"fc-{uuid.uuid4().hex[:10]}",
        created_at=datetime.now(UTC).isoformat(timespec="seconds"),
        t0_s=t0,
        horizon_min=horizon_min,
        n_members=n_members,
        state_source=state_source,
        estimate=estimate if state_source == "estimated" else None,
        baseline_branch_id="baseline",
        branches=outcomes,
        ranking=ranking,
        seeds=seeds,
        objective_definition=OBJECTIVE_DEFINITION,
        assumptions=ASSUMPTIONS,
        compute_ms=(time.perf_counter() - start) * 1000.0,
    )
