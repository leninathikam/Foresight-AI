"""Deterministic, LLM-independent verification of proposed interventions.

The verifier only trusts (a) the proposal's typed parameters, (b) a FutureComparison produced
by the branching engine for the *current* machine state, and (c) the latest risk assessment.
It never reads LLM free text as evidence. Any blocking check failure rejects the proposal.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from foresight.branching import ACTION_ADAPTER, FutureComparison, compare_futures
from foresight.prediction.schemas import RiskAssessment
from foresight.simulation import (
    DEFAULT_MOTOR,
    Action,
    ContinueOperation,
    ControlledShutdown,
    IncreaseCooling,
    MotorTwin,
    ReduceLoad,
    ReduceSpeed,
    ScheduleInspection,
    describe_action,
)

# Planning comparisons use base seeds 0, 1, 2, ... (one per comparison in a run), so this offset
# guarantees the verifier's ensemble never shares disturbance seeds with the proposer's.
CONFIRMATION_BASE_SEED = 900


class SafetyPolicy(BaseModel):
    """Operating envelope. Margins are deliberately conservative relative to failure limits."""

    max_branch_temperature_c: float = DEFAULT_MOTOR.temperature_failure_c - 15.0  # 140 °C
    # 1 mm/s below the trip (6.1 mm/s): branches whose p90 sits just under the trip still fail
    # in larger ensembles (found by the red-team).
    max_branch_vibration_mm_s: float = DEFAULT_MOTOR.vibration_trip_mm_s - 1.0
    max_continuous_load: float = DEFAULT_MOTOR.max_safe_load_fraction
    max_failure_incidence: float = 0.0
    max_failure_upper_ci: float = 0.40
    min_members: int = 8
    max_temperature_spread_k: float = 20.0
    reduce_load_range: tuple[float, float] = (0.05, 0.5)
    reduce_speed_range: tuple[float, float] = (0.05, 0.4)
    aux_cooling_capacity: float = DEFAULT_MOTOR.max_aux_cooling_boost
    inspection_delay_range_min: tuple[float, float] = (0.0, 480.0)
    inspection_lead_margin_min: float = 15.0
    max_state_age_s: float = 600.0
    confirmation_members: int = 16
    # Reject consequential actions that neither lower the objective nor prevent a simulated
    # failure. False reproduces the pre-red-team verifier, which only warned.
    block_no_benefit: bool = True
    # A tie with doing nothing is not a benefit, and an inspection that starts after the
    # simulated horizon has no simulated effect, so neither can be verified.
    strict_improvement: bool = True
    # Inspection lead time is measured from the baseline's earliest simulated failure, not the
    # median: with a spread of failure times, early-failing members fail before a
    # median-timed inspection starts (found by the red-team).
    inspection_before_earliest_failure: bool = True


DEFAULT_POLICY = SafetyPolicy()

CheckStatus = Literal["pass", "fail", "warn", "skip"]


class CheckResult(BaseModel):
    name: str
    status: CheckStatus
    blocking: bool
    detail: str
    measured: float | str | None = None
    limit: float | str | None = None


class Proposal(BaseModel):
    action: Action
    claimed_failure_mode: Literal["thermal", "bearing", "overload", "none", "unknown"] = "unknown"
    cited_evidence_ids: list[str] = Field(default_factory=list)
    source: Literal["agent", "user", "rule_baseline", "optimizer"] = "user"


class VerificationResult(BaseModel):
    verdict: Literal["accepted", "accepted_with_warnings", "rejected"]
    action: dict
    action_label: str
    checks: list[CheckResult]
    requires_human_approval: bool
    rejection_reasons: list[str]
    comparison_id: str | None
    summary: str


CONSEQUENTIAL = (ReduceLoad, ReduceSpeed, IncreaseCooling, ScheduleInspection, ControlledShutdown)


def _check_parameters(action: Action, policy: SafetyPolicy) -> CheckResult:
    def rng(name: str, value: float, bounds: tuple[float, float], unit: str = "") -> CheckResult:
        ok = bounds[0] <= value <= bounds[1]
        return CheckResult(
            name="action_parameters_valid",
            status="pass" if ok else "fail",
            blocking=True,
            detail=f"{name}={value:g}{unit} must lie in [{bounds[0]:g}, {bounds[1]:g}]{unit}",
            measured=value,
            limit=f"{bounds[0]:g}–{bounds[1]:g}",
        )

    match action:
        case ReduceLoad(fraction=f):
            return rng("fraction", f, policy.reduce_load_range)
        case ReduceSpeed(fraction=f):
            return rng("fraction", f, policy.reduce_speed_range)
        case IncreaseCooling(boost=b):
            return rng("boost", b, (0.01, 1.0))
        case ScheduleInspection(delay_minutes=d):
            return rng("delay_minutes", d, policy.inspection_delay_range_min, " min")
    return CheckResult(
        name="action_parameters_valid", status="pass", blocking=True, detail="No parameters"
    )


def _check_feasibility(
    action: Action, comparison: FutureComparison, policy: SafetyPolicy
) -> CheckResult:
    if isinstance(action, IncreaseCooling) and action.boost > policy.aux_cooling_capacity + 1e-9:
        return CheckResult(
            name="intervention_feasible",
            status="fail",
            blocking=True,
            detail=(
                f"Auxiliary blower capacity is {policy.aux_cooling_capacity:.0%} extra airflow; "
                f"{action.boost:.0%} is not achievable (the simulator would silently saturate)"
            ),
            measured=action.boost,
            limit=policy.aux_cooling_capacity,
        )
    if (
        isinstance(action, ScheduleInspection)
        and policy.strict_improvement
        and action.delay_minutes >= comparison.horizon_min
    ):
        return CheckResult(
            name="intervention_feasible",
            status="fail",
            blocking=True,
            detail=(
                f"Inspection in {action.delay_minutes:.0f} min starts after the "
                f"{comparison.horizon_min:.0f}-min simulated horizon, so its effect cannot be verified"
            ),
            measured=action.delay_minutes,
            limit=comparison.horizon_min,
        )
    if isinstance(action, ScheduleInspection):
        base = next(b for b in comparison.branches if b.branch_id == comparison.baseline_branch_id)
        use_earliest = (
            policy.inspection_before_earliest_failure
            and base.earliest_time_to_failure_min is not None
        )
        ref = base.earliest_time_to_failure_min if use_earliest else base.median_time_to_failure_min
        if ref is not None:
            latest = ref - policy.inspection_lead_margin_min
            ok = action.delay_minutes <= latest
            return CheckResult(
                name="intervention_feasible",
                status="pass" if ok else "fail",
                blocking=True,
                detail=(
                    f"Inspection must start ≥{policy.inspection_lead_margin_min:.0f} min before the "
                    f"baseline {'earliest' if use_earliest else 'median'} simulated failure "
                    f"({ref:.0f} min)"
                ),
                measured=action.delay_minutes,
                limit=round(latest, 1),
            )
    return CheckResult(
        name="intervention_feasible", status="pass", blocking=True, detail="Feasible"
    )


def independent_confirmation(
    action: Action,
    comparison: FutureComparison | None,
    oracle_twin: MotorTwin | None = None,
    policy: SafetyPolicy = DEFAULT_POLICY,
) -> FutureComparison | None:
    """Re-simulate a proposed action from the comparison's initial state with verifier-owned seeds.

    The proposer chooses which actions to simulate and can (deliberately or by chance) select an
    action whose small ensemble happened to avoid failure. A fresh, larger ensemble with seeds the
    proposer never saw removes that selection effect. Returns None when there is nothing to
    confirm (no simulated branch, continue_operation, or missing initial state).
    """
    if comparison is None or isinstance(action, ContinueOperation):
        return None
    if comparison.branch_for_action(action) is None:
        return None
    if comparison.state_source == "oracle":
        if oracle_twin is None:
            return None
        source: dict = {"state_source": "oracle", "oracle_twin": oracle_twin}
    else:
        if comparison.estimate is None:
            return None
        source = {"state_source": "estimated", "estimate": comparison.estimate}
    return compare_futures(
        [action],
        horizon_min=comparison.horizon_min,
        n_members=policy.confirmation_members,
        base_seed=CONFIRMATION_BASE_SEED,
        **source,
    )


def _check_confirmation(
    action: Action, confirmation: FutureComparison | None, policy: SafetyPolicy
) -> CheckResult:
    if isinstance(action, ContinueOperation):
        return CheckResult(
            name="independent_confirmation",
            status="skip",
            blocking=False,
            detail="Continue operation is the baseline; nothing to confirm",
        )
    branch = confirmation.branch_for_action(action) if confirmation else None
    if branch is None:
        return CheckResult(
            name="independent_confirmation",
            status="fail",
            blocking=True,
            detail="Verifier could not re-simulate this action with its own ensemble",
        )
    lo, hi = branch.failure_incidence_ci95
    ok = (
        branch.failure_incidence <= policy.max_failure_incidence
        and branch.peak_temperature_p90_c <= policy.max_branch_temperature_c
        and branch.peak_vibration_p90_mm_s <= policy.max_branch_vibration_mm_s
    )
    return CheckResult(
        name="independent_confirmation",
        status="pass" if ok else "fail",
        blocking=True,
        detail=(
            f"Verifier re-simulation with {branch.n_members} independent members: failure "
            f"incidence {branch.failure_incidence:.0%} (95 % CI {lo:.2f}–{hi:.2f}), p90 peak "
            f"{branch.peak_temperature_p90_c:.1f} °C / {branch.peak_vibration_p90_mm_s:.2f} mm/s"
        ),
        measured=round(branch.failure_incidence, 3),
        limit=policy.max_failure_incidence,
    )


def verify(
    proposal: Proposal,
    comparison: FutureComparison | None,
    assessment: RiskAssessment | None,
    now_s: float,
    known_evidence_ids: set[str] | None = None,
    policy: SafetyPolicy = DEFAULT_POLICY,
    confirmation: FutureComparison | None = None,
    require_confirmation: bool = True,
) -> VerificationResult:
    action = proposal.action
    checks: list[CheckResult] = [_check_parameters(action, policy)]

    branch = comparison.branch_for_action(action) if comparison else None
    if comparison is None or branch is None:
        checks.append(
            CheckResult(
                name="simulation_complete",
                status="fail",
                blocking=True,
                detail="No simulated future exists for this exact action; it must be simulated first",
            )
        )
    else:
        age = now_s - comparison.t0_s
        complete = (
            branch.n_members >= policy.min_members
            and len(branch.temperature_band.t_min) > 0
            and abs(branch.temperature_band.t_min[-1] - comparison.horizon_min) <= 1.0
        )
        checks.append(
            CheckResult(
                name="simulation_complete",
                status="pass" if complete and age <= policy.max_state_age_s else "fail",
                blocking=True,
                detail=(
                    f"{branch.n_members} members over {comparison.horizon_min:.0f} min; "
                    f"simulated from state {age / 60:.1f} min old (max {policy.max_state_age_s / 60:.0f})"
                ),
                measured=branch.n_members,
                limit=policy.min_members,
            )
        )
        checks.append(_check_feasibility(action, comparison, policy))
        checks.append(
            CheckResult(
                name="temperature_limit",
                status="pass"
                if branch.peak_temperature_p90_c <= policy.max_branch_temperature_c
                else "fail",
                blocking=True,
                detail="90th-percentile peak winding temperature across the ensemble",
                measured=round(branch.peak_temperature_p90_c, 1),
                limit=policy.max_branch_temperature_c,
            )
        )
        checks.append(
            CheckResult(
                name="vibration_limit",
                status="pass"
                if branch.peak_vibration_p90_mm_s <= policy.max_branch_vibration_mm_s
                else "fail",
                blocking=True,
                detail="90th-percentile peak vibration while running",
                measured=round(branch.peak_vibration_p90_mm_s, 2),
                limit=policy.max_branch_vibration_mm_s,
            )
        )
        checks.append(
            CheckResult(
                name="load_range",
                status="pass"
                if branch.max_running_load <= policy.max_continuous_load + 0.02
                else "fail",
                blocking=True,
                detail="Maximum applied load while running (2 % tolerance for process noise)",
                measured=round(branch.max_running_load, 3),
                limit=policy.max_continuous_load,
            )
        )
        lo, hi = branch.failure_incidence_ci95
        checks.append(
            CheckResult(
                name="failure_risk",
                status="pass"
                if branch.failure_incidence <= policy.max_failure_incidence
                else "fail",
                blocking=True,
                detail=f"Simulated failures in {branch.n_members} members (95 % CI {lo:.2f}–{hi:.2f})",
                measured=round(branch.failure_incidence, 3),
                limit=policy.max_failure_incidence,
            )
        )
        spread = max(
            p90 - p10
            for p10, p90 in zip(
                branch.temperature_band.p10, branch.temperature_band.p90, strict=True
            )
        )
        uncertain = hi > policy.max_failure_upper_ci or spread > policy.max_temperature_spread_k
        checks.append(
            CheckResult(
                name="uncertainty",
                status="warn" if uncertain else "pass",
                blocking=False,
                detail=(
                    f"Failure-rate upper bound {hi:.2f} (limit {policy.max_failure_upper_ci}); "
                    f"max p10–p90 temperature spread {spread:.1f} K (limit {policy.max_temperature_spread_k})"
                ),
                measured=round(hi, 3),
                limit=policy.max_failure_upper_ci,
            )
        )
        base = next(b for b in comparison.branches if b.branch_id == comparison.baseline_branch_id)
        cheaper = (
            branch.objective < base.objective
            if policy.strict_improvement
            else branch.objective <= base.objective
        )
        better = cheaper or branch.failure_incidence < base.failure_incidence
        # An intervention that neither lowers the objective nor prevents any simulated failure
        # only adds cost and downtime; it must not reach the operator as a recommendation.
        consequential = isinstance(action, CONSEQUENTIAL)
        blocking = consequential and policy.block_no_benefit
        checks.append(
            CheckResult(
                name="improves_on_baseline",
                status="pass" if better or not consequential else ("fail" if blocking else "warn"),
                blocking=blocking,
                detail=(
                    f"Objective {branch.objective:,.0f} vs no-action {base.objective:,.0f}; failure "
                    f"incidence {branch.failure_incidence:.0%} vs {base.failure_incidence:.0%}"
                    + ("" if better or not consequential else " — no simulated benefit")
                ),
                measured=round(branch.objective, 1),
                limit=round(base.objective, 1),
            )
        )
        if require_confirmation:
            checks.append(_check_confirmation(action, confirmation, policy))

    checks.extend(_evidence_checks(proposal, assessment, known_evidence_ids))

    failures = [c for c in checks if c.blocking and c.status == "fail"]
    warnings = [c for c in checks if c.status == "warn"]
    verdict = "rejected" if failures else ("accepted_with_warnings" if warnings else "accepted")
    label = describe_action(action)
    if failures:
        summary = f"Rejected '{label}': " + "; ".join(f"{c.name} ({c.detail})" for c in failures)
    else:
        summary = f"'{label}' passed all blocking checks" + (
            f" with {len(warnings)} warning(s)" if warnings else ""
        )
    return VerificationResult(
        verdict=verdict,
        action=ACTION_ADAPTER.dump_python(action, mode="json"),
        action_label=label,
        checks=checks,
        requires_human_approval=isinstance(action, CONSEQUENTIAL) and not failures,
        rejection_reasons=[f"{c.name}: {c.detail}" for c in failures],
        comparison_id=comparison.id if comparison else None,
        summary=summary,
    )


def verify_independently(
    proposal: Proposal,
    comparison: FutureComparison | None,
    assessment: RiskAssessment | None,
    now_s: float,
    known_evidence_ids: set[str] | None = None,
    oracle_twin: MotorTwin | None = None,
    policy: SafetyPolicy = DEFAULT_POLICY,
) -> VerificationResult:
    """Full verification: the proposer's comparison plus the verifier's own re-simulation.

    CPU-bound (one extra ensemble); call it via asyncio.to_thread from async code."""
    confirmation = independent_confirmation(proposal.action, comparison, oracle_twin, policy)
    return verify(
        proposal,
        comparison,
        assessment,
        now_s,
        known_evidence_ids=known_evidence_ids,
        policy=policy,
        confirmation=confirmation,
    )


def _evidence_checks(
    proposal: Proposal, assessment: RiskAssessment | None, known_ids: set[str] | None
) -> list[CheckResult]:
    checks: list[CheckResult] = []
    if known_ids is not None and proposal.cited_evidence_ids:
        unknown = [e for e in proposal.cited_evidence_ids if e not in known_ids]
        checks.append(
            CheckResult(
                name="evidence_exists",
                status="fail" if unknown else "pass",
                blocking=True,
                detail=(
                    f"Cited evidence not found in the evidence registry: {', '.join(unknown)}"
                    if unknown
                    else f"All {len(proposal.cited_evidence_ids)} cited evidence ids exist"
                ),
            )
        )
    if (
        assessment is None
        or not assessment.available
        or proposal.claimed_failure_mode in ("unknown", "none")
    ):
        checks.append(
            CheckResult(
                name="evidence_consistency",
                status="skip",
                blocking=False,
                detail="No failure mode claimed",
            )
        )
        return checks
    f = assessment.features
    support = {
        "thermal": f.get("rise_residual_k", 0) > 5
        or f.get("temp_slope_30m", 0) > 0.1
        or f.get("temperature_c", 0) > 125,
        "bearing": f.get("bearing_index", 0) > 0.15 or f.get("vibration_mm_s", 0) > 2.8,
        "overload": f.get("load_frac", 0) > 1.0 or f.get("load_slope_30m", 0) > 0.002,
    }[proposal.claimed_failure_mode]
    checks.append(
        CheckResult(
            name="evidence_consistency",
            status="pass" if support else "warn",
            blocking=False,
            detail=(
                f"Claimed '{proposal.claimed_failure_mode}' mode is "
                + ("supported" if support else "NOT supported")
                + " by current observed features"
            ),
        )
    )
    return checks
