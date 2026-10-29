"""Active information gathering: should a verified action wait for more telemetry?

A verified consequential action is deferred, and more telemetry gathered, only when both hold:

1. The risk that motivates it rests on trends the telemetry does not yet support. Each trend
   that drives the forecast (cooling fouling, bearing damage growth, load ramp) is tested with
   the standard error of its fit; trends with t < 2 are unsupported. With the unsupported trends
   removed (current levels kept), the no-action ensemble must show no failure, no alarm-zone
   ending and no limit exceedance.
2. Waiting is safe. With every trend kept and each spread widened to its fit's standard error,
   the no-action ensemble on seeds the planner and verifier never use must show no failure and
   stay within the temperature and vibration limits until the deferral window plus the
   inspection lead margin has passed.

Otherwise the verified action stands. The decision is deterministic and LLM-independent.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from foresight.branching import BranchOutcome, StateEstimate, compare_futures
from foresight.branching.estimation import DETECTABLE_DAMAGE
from foresight.verification.verifier import DEFAULT_POLICY, SafetyPolicy

TREND_T_MIN = 2.0
DEFER_MINUTES = 15.0
INFO_MEMBERS = 16
# Planning comparisons use base seeds 0, 1, 2, ...; the verifier uses 900.
INFO_BASE_SEED = 950

TrendName = Literal["cooling_fouling", "bearing_growth", "load_ramp"]


class TrendEvidence(BaseModel):
    name: TrendName
    value_per_h: float
    se_per_h: float | None
    t_stat: float | None
    drives_forecast: bool
    supported: bool


class InformationAssessment(BaseModel):
    decision: Literal["act_now", "gather_information"]
    defer_minutes: float
    trends: list[TrendEvidence]
    unsupported_trends: list[TrendName]
    without_unsupported: dict | None = None
    waiting: dict | None = None
    reasons: list[str]
    summary: str


def _trends(est: StateEstimate) -> list[TrendEvidence]:
    rows: list[tuple[TrendName, float, float | None, bool]] = [
        (
            "cooling_fouling",
            max(0.0, -est.cooling_trend_per_h),
            est.cooling_trend_se_per_h,
            -est.cooling_trend_per_h > 0.02,
        ),
        (
            "bearing_growth",
            est.bearing_growth_per_h,
            est.bearing_growth_se_per_h,
            est.bearing_damage > DETECTABLE_DAMAGE and est.bearing_growth_per_h > 0,
        ),
        (
            "load_ramp",
            est.load_trend_per_h,
            est.load_trend_se_per_h,
            est.load_trend_per_h > 0.03,
        ),
    ]
    out = []
    for name, value, se, drives in rows:
        t = value / se if se else None
        out.append(
            TrendEvidence(
                name=name,
                value_per_h=round(value, 4),
                se_per_h=None if se is None else round(se, 4),
                t_stat=None if t is None else round(t, 2),
                drives_forecast=drives,
                supported=se == 0 or (t is not None and t >= TREND_T_MIN),
            )
        )
    return out


def _without(est: StateEstimate, names: list[TrendName]) -> StateEstimate:
    update: dict = {}
    if "cooling_fouling" in names:
        update["cooling_trend_per_h"] = 0.0
    if "bearing_growth" in names:
        update["bearing_growth_per_h"] = 0.0
    if "load_ramp" in names:
        update["load_trend_per_h"] = 0.0
        update["baseline_process_load"] = est.process_load
    return est.model_copy(update=update)


def _within_limits(b: BranchOutcome, policy: SafetyPolicy) -> bool:
    return (
        b.peak_temperature_p90_c <= policy.max_branch_temperature_c
        and b.peak_vibration_p90_mm_s <= policy.max_branch_vibration_mm_s
    )


def _band_within(b: BranchOutcome, until_min: float, policy: SafetyPolicy) -> bool:
    temps = [
        p90
        for t, p90 in zip(b.temperature_band.t_min, b.temperature_band.p90, strict=True)
        if t <= until_min
    ]
    vibs = [
        p90
        for t, p90 in zip(b.vibration_band.t_min, b.vibration_band.p90, strict=True)
        if t <= until_min
    ]
    return (
        max(temps, default=0.0) <= policy.max_branch_temperature_c
        and max(vibs, default=0.0) <= policy.max_branch_vibration_mm_s
    )


def assess_information_value(
    est: StateEstimate,
    horizon_min: float = 180.0,
    defer_minutes: float = DEFER_MINUTES,
    policy: SafetyPolicy = DEFAULT_POLICY,
) -> InformationAssessment:
    """Decide whether to act now or gather ``defer_minutes`` more telemetry first.

    CPU-bound (up to two 16-member no-action ensembles); call via asyncio.to_thread."""
    trends = _trends(est)
    unsupported: list[TrendName] = [t.name for t in trends if t.drives_forecast and not t.supported]
    driving = [t.name for t in trends if t.drives_forecast]

    def result(decision, reasons, summary, **kw) -> InformationAssessment:
        return InformationAssessment(
            decision=decision,
            defer_minutes=defer_minutes,
            trends=trends,
            unsupported_trends=unsupported,
            reasons=reasons,
            summary=summary,
            **kw,
        )

    if not unsupported:
        why = (
            f"Every trend driving the forecast is statistically supported (t ≥ {TREND_T_MIN:g}): "
            + ", ".join(driving)
            if driving
            else "The forecast rests on current levels, not on trends"
        )
        return result("act_now", [why], f"{why}; more telemetry would not change the decision.")

    null = compare_futures(
        [],
        horizon_min=horizon_min,
        n_members=INFO_MEMBERS,
        base_seed=INFO_BASE_SEED,
        estimate=_without(est, unsupported),
    ).branches[0]
    without = {
        "failure_incidence": round(null.failure_incidence, 3),
        "end_alarm_fraction": round(null.end_alarm_fraction, 3),
        "peak_temperature_p90_c": round(null.peak_temperature_p90_c, 1),
        "peak_vibration_p90_mm_s": round(null.peak_vibration_p90_mm_s, 2),
    }
    if (
        null.failure_incidence > 0
        or null.end_alarm_fraction > 0
        or not _within_limits(null, policy)
    ):
        why = (
            f"Risk remains without the unsupported trend(s) {', '.join(unsupported)}: "
            f"failure incidence {null.failure_incidence:.0%}, alarm at horizon "
            f"{null.end_alarm_fraction:.0%}, p90 peak {null.peak_temperature_p90_c:.1f} °C"
        )
        return result("act_now", [why], why + ".", without_unsupported=without)

    wait = compare_futures(
        [],
        horizon_min=horizon_min,
        n_members=INFO_MEMBERS,
        base_seed=INFO_BASE_SEED + 1,
        estimate=est,
        trend_uncertainty="standard_error",
    ).branches[0]
    needed = defer_minutes + policy.inspection_lead_margin_min
    earliest = wait.earliest_time_to_failure_min
    safe = (earliest is None or earliest > needed) and _band_within(wait, needed, policy)
    waiting = {
        "members": wait.n_members,
        "failure_incidence": round(wait.failure_incidence, 3),
        "earliest_failure_min": None if earliest is None else round(earliest, 1),
        "required_failure_free_min": needed,
    }
    weak = ", ".join(
        f"{t.name} t={t.t_stat if t.t_stat is not None else 'n/a'}"
        for t in trends
        if t.name in unsupported
    )
    if not safe:
        why = (
            f"The risk rests on unsupported trend(s) ({weak}), but waiting is not safe: with fit "
            f"uncertainty propagated, the earliest simulated failure is at "
            f"{earliest if earliest is None else round(earliest)} min (need > {needed:.0f} min)"
        )
        return result("act_now", [why], why + ".", without_unsupported=without, waiting=waiting)
    reasons = [
        f"Unsupported trend(s) drive the forecast: {weak} (need t ≥ {TREND_T_MIN:g})",
        "Without them the no-action future has no failure and no alarm "
        f"(p90 peak {null.peak_temperature_p90_c:.1f} °C)",
        f"Waiting is safe: no simulated failure within {needed:.0f} min across "
        f"{wait.n_members} members with fit uncertainty propagated"
        + ("" if earliest is None else f" (earliest at {earliest:.0f} min)"),
    ]
    return result(
        "gather_information",
        reasons,
        f"Gather {defer_minutes:.0f} more minutes of telemetry before acting: the risk rests on "
        f"trend(s) the data does not yet support ({weak}), and waiting is safe.",
        without_unsupported=without,
        waiting=waiting,
    )
