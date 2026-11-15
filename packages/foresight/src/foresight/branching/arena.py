"""Future Arena: 3-way head-to-head counterfactual scenario simulation.

Compares:
1. Continue Operating (Baseline / Do Nothing)
2. Reduce Load (Operational derating to buy time / reduce stress)
3. Planned Maintenance (Scheduled inspection & root-cause repair)

Uses the deterministic Future Branching engine with common random numbers,
computes empirical risk, downtime, cost breakdowns, and routes each branch
through independent Verifier v5 safety checks.
"""

from __future__ import annotations

import time
from typing import Any, Literal

from pydantic import BaseModel, Field

from foresight.branching.engine import (
    Band,
    BranchOutcome,
    CostBreakdown,
    FutureComparison,
    compare_futures,
)
from foresight.branching.estimation import StateEstimate
from foresight.prediction.schemas import RiskAssessment
from foresight.simulation import (
    Action,
    ContinueOperation,
    MotorTwin,
    ReduceLoad,
    ScheduleInspection,
    describe_action,
)
from foresight.verification.verifier import (
    SafetyPolicy,
    VerificationResult,
    verify_independently,
)


class ArenaScenarioResult(BaseModel):
    scenario_id: str = Field(description="continue_operating | reduce_load | planned_maintenance")
    label: str = Field(description="Descriptive scenario label")
    action: dict[str, Any] = Field(description="Action parameters")
    failure_incidence: float = Field(description="Empirical failure rate across ensemble")
    failure_incidence_ci95: tuple[float, float] = Field(description="Wilson 95% confidence interval")
    peak_temperature_p90_c: float = Field(description="90th percentile peak winding temperature")
    peak_vibration_p90_mm_s: float = Field(description="90th percentile peak vibration velocity")
    expected_cost_usd: float = Field(description="Mean total economic cost in USD")
    cost_breakdown: CostBreakdown = Field(description="Detailed cost components")
    downtime_mean_h: float = Field(description="Expected hours of asset downtime")
    objective_score: float = Field(description="Combined loss score (lower is better)")
    temperature_band: Band = Field(description="Ensemble trajectory band (p10, p50, p90)")
    vibration_band: Band = Field(description="Ensemble vibration trajectory band")
    safety_status: Literal["accepted", "accepted_with_warnings", "rejected"]
    safety_summary: str
    rejection_reasons: list[str] = Field(default_factory=list)
    decision_hash: str = Field(default="")
    is_best_objective: bool = False
    evidence_id: str = Field(description="Cryptographic trace evidence identifier")


class FutureArenaComparison(BaseModel):
    arena_id: str
    session_id: str
    timestamp_utc: str
    t0_min: float
    horizon_min: float
    members: int
    reproducible_base_seed: int
    seeds: list[int]
    scenarios: list[ArenaScenarioResult]
    winner_scenario_id: str
    winner_label: str
    recommendation_reason: str
    comparison_id: str
    compute_ms: float
    assumptions: list[str]
    provenance_note: str = Field(
        default="All scenarios simulated from identical estimated initial states using common random numbers (CRN)."
    )


def run_future_arena(
    *,
    session_id: str,
    t0_s: float,
    estimate: StateEstimate,
    assessment: RiskAssessment | None = None,
    horizon_min: float = 180.0,
    members: int = 8,
    reduce_load_fraction: float = 0.30,
    inspection_delay_min: float = 15.0,
    base_seed: int = 42,
    oracle_twin: MotorTwin | None = None,
    policy: SafetyPolicy | None = None,
) -> FutureArenaComparison:
    """Execute the head-to-head 3-way Future Arena comparison."""
    start = time.perf_counter()

    actions: list[Action] = [
        ContinueOperation(),
        ReduceLoad(fraction=reduce_load_fraction),
        ScheduleInspection(delay_minutes=inspection_delay_min),
    ]

    comp = compare_futures(
        actions=actions,
        horizon_min=horizon_min,
        n_members=members,
        base_seed=base_seed,
        state_source="estimated",
        estimate=estimate,
        oracle_twin=oracle_twin,
    )

    scenarios_results: list[ArenaScenarioResult] = []
    best_id = comp.ranking[0] if comp.ranking else ""

    known_ids: set[str] = set()
    if assessment:
        known_ids = {e.id for e in assessment.evidence}
    for b in comp.branches:
        known_ids.add(f"sim:{comp.id}:{b.branch_id}")

    scenario_type_map = {
        "continue_operation": "continue_operating",
        "reduce_load": "reduce_load",
        "schedule_inspection": "planned_maintenance",
    }

    for b in comp.branches:
        action_type = b.action.get("type", "continue_operation")
        scenario_key = scenario_type_map.get(action_type, b.branch_id)

        # Run independent verification
        proposal_action = (
            ContinueOperation()
            if action_type == "continue_operation"
            else ReduceLoad(fraction=reduce_load_fraction)
            if action_type == "reduce_load"
            else ScheduleInspection(delay_minutes=inspection_delay_min)
        )
        from foresight.verification.verifier import Proposal

        raw_mode = "unknown"
        if assessment and assessment.diagnosis:
            lbl = assessment.diagnosis[0].label.lower()
            if "cool" in lbl or "therm" in lbl:
                raw_mode = "thermal"
            elif "bear" in lbl or "vib" in lbl:
                raw_mode = "bearing"
            elif "overload" in lbl:
                raw_mode = "overload"
            elif "none" in lbl or "healthy" in lbl:
                raw_mode = "none"

        prop = Proposal(
            action=proposal_action,
            claimed_failure_mode=raw_mode,
            cited_evidence_ids=[f"sim:{comp.id}:{b.branch_id}"],
            source="optimizer",
        )

        v_res = verify_independently(
            prop,
            comp,
            assessment,
            policy=policy,
            now_s=t0_s,
            known_evidence_ids=known_ids,
        )

        scenarios_results.append(
            ArenaScenarioResult(
                scenario_id=scenario_key,
                label=b.label,
                action=b.action,
                failure_incidence=round(b.failure_incidence, 4),
                failure_incidence_ci95=b.failure_incidence_ci95,
                peak_temperature_p90_c=round(b.peak_temperature_p90_c, 1),
                peak_vibration_p90_mm_s=round(b.peak_vibration_p90_mm_s, 2),
                expected_cost_usd=round(b.cost_mean, 2),
                cost_breakdown=b.cost_breakdown_mean,
                downtime_mean_h=round(b.downtime_mean_h, 2),
                objective_score=round(b.objective, 2),
                temperature_band=b.temperature_band,
                vibration_band=b.vibration_band,
                safety_status=v_res.verdict,
                safety_summary=v_res.summary,
                rejection_reasons=v_res.rejection_reasons,
                decision_hash=v_res.decision_hash,
                is_best_objective=(b.branch_id == best_id),
                evidence_id=f"sim:{comp.id}:{b.branch_id}",
            )
        )

    # Determine recommended scenario (lowest objective that is accepted or accepted_with_warnings)
    accepted_scenarios = [s for s in scenarios_results if s.safety_status != "rejected"]
    if accepted_scenarios:
        winner = min(accepted_scenarios, key=lambda s: s.objective_score)
        reason = (
            f"Scenario '{winner.label}' achieves the lowest expected economic impact (${winner.expected_cost_usd:,.0f}) "
            f"while strictly satisfying all physical safety and ISO limits."
        )
    else:
        winner = min(scenarios_results, key=lambda s: s.objective_score)
        reason = (
            f"All scenarios received safety verifier rejection flags; '{winner.label}' had the lowest unverified loss score. "
            "Controlled shutdown is advised until maintenance is completed."
        )

    from datetime import datetime, timezone

    return FutureArenaComparison(
        arena_id=f"arena-{comp.id}",
        session_id=session_id,
        timestamp_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        t0_min=round(t0_s / 60.0, 1),
        horizon_min=horizon_min,
        members=members,
        reproducible_base_seed=base_seed,
        seeds=comp.seeds,
        scenarios=scenarios_results,
        winner_scenario_id=winner.scenario_id,
        winner_label=winner.label,
        recommendation_reason=reason,
        comparison_id=comp.id,
        compute_ms=round((time.perf_counter() - start) * 1000.0, 1),
        assumptions=comp.assumptions,
    )
