"""Calibration of counterfactual predictions against the hidden true process.

At held-out decision points (no intervention applied yet) the planner's estimated-state ensemble
predicts each candidate action's outcome. The reference is the same action simulated from the
twin's hidden true state with fresh disturbance seeds: each reference member is one realisation
of the true process. This isolates state-estimation and parameter uncertainty; model-form error
is out of scope because both sides use the same twin equations.

Two uncertainty models are compared: the fixed trend spread the planner uses, and the spread
widened to each trend fit's standard error.

The true state includes the episode's fault schedule, so at a decision point before fault onset
the reference can fail from a fault that no telemetry could reveal yet. Results are therefore
also split by fault state at the decision point: no fault, latent (scheduled but not started)
and active.
"""

from __future__ import annotations

from typing import Literal

import numpy as np
from joblib import Parallel, delayed

from foresight.branching import (
    ActuatorSettings,
    FutureComparison,
    compare_futures,
    estimate_state,
)
from foresight.prediction.dataset import SPLIT_SEEDS
from foresight.simulation import (
    Action,
    EpisodeConfig,
    IncreaseCooling,
    ReduceLoad,
    ScenarioId,
    ScheduleInspection,
    describe_action,
    sample_episode,
)
from foresight.telemetry import TelemetryStream

ACTIONS: tuple[Action, ...] = (
    ReduceLoad(fraction=0.3),
    IncreaseCooling(boost=0.4),
    ScheduleInspection(delay_minutes=10),
)
DECISION_MINUTES = (60, 120, 180)
MEMBERS = 16
REFERENCE_SEED = 500
HORIZON_MIN = 180.0
MODES = ("fixed", "standard_error")
FaultState = Literal["no_fault", "latent", "active"]
FAULT_STATES: tuple[FaultState, ...] = ("no_fault", "latent", "active")


def _fault_onset_min(episode: EpisodeConfig) -> float | None:
    f = episode.fault
    onset = f.cooling_fouling_onset_s or f.bearing_defect_onset_s or f.overload_onset_s
    return None if onset is None else round(onset / 60.0, 1)


def _decision_point(scenario: ScenarioId, seed: int, minute: int) -> dict | None:
    episode = sample_episode(scenario, seed)
    onset = _fault_onset_min(episode)
    stream = TelemetryStream(episode)
    stream.advance(minute * 60.0)
    if stream.twin.state.failed:
        return None
    s = stream.twin.state
    actuators = ActuatorSettings(
        load_multiplier=s.load_multiplier, speed_setpoint=s.speed_setpoint, aux_boost=s.aux_boost
    )
    try:
        est = estimate_state(list(stream.window)[-720:], actuators)
    except ValueError:
        return None
    reference = compare_futures(
        ACTIONS,
        horizon_min=HORIZON_MIN,
        n_members=MEMBERS,
        base_seed=REFERENCE_SEED,
        state_source="oracle",
        oracle_twin=stream.twin.clone(),
    )
    predicted = {
        mode: compare_futures(
            ACTIONS,
            horizon_min=HORIZON_MIN,
            n_members=MEMBERS,
            base_seed=0,
            estimate=est,
            trend_uncertainty=mode,
        )
        for mode in MODES
    }
    return {
        "scenario": scenario.value,
        "seed": seed,
        "minute": minute,
        "fault_onset_min": onset,
        "fault_state": _fault_state(onset, minute),
        "rows": {mode: _rows(comp, reference) for mode, comp in predicted.items()},
        "decision": {mode: _decision(comp, reference) for mode, comp in predicted.items()},
    }


def _fault_state(onset_min: float | None, minute: int) -> FaultState:
    if onset_min is None:
        return "no_fault"
    return "active" if onset_min <= minute else "latent"


def _rows(pred: FutureComparison, ref: FutureComparison) -> list[dict]:
    rows = []
    for pb, rb in zip(pred.branches, ref.branches, strict=True):
        p_peaks = np.array([m.peak_temperature_c for m in pb.members])
        lo, hi = np.percentile(p_peaks, [10, 90])
        r_peaks = np.array([m.peak_temperature_c for m in rb.members])
        rows.append(
            {
                "action": pb.label,
                "p_hat": pb.failure_incidence,
                "outcomes": [int(m.failed) for m in rb.members],
                "p_ref": rb.failure_incidence,
                "peak_in_band": float(np.mean((r_peaks >= lo) & (r_peaks <= hi))),
                "peak_median_error_k": float(np.median(p_peaks) - np.median(r_peaks)),
            }
        )
    return rows


def _decision(pred: FutureComparison, ref: FutureComparison) -> dict:
    chosen = pred.ranking[0]
    ref_by_id = {b.branch_id: b for b in ref.branches}
    best = min(ref.branches, key=lambda b: b.objective)
    return {
        "chosen": next(b.label for b in pred.branches if b.branch_id == chosen),
        "reference_best": best.label,
        "regret_usd": round(ref_by_id[chosen].objective - best.objective, 1),
    }


def _summarise(points: list[dict], mode: str) -> dict:
    rows = [r for p in points for r in p["rows"][mode]]
    if not rows:
        return {}
    p_hat = np.repeat([r["p_hat"] for r in rows], [len(r["outcomes"]) for r in rows])
    y = np.concatenate([r["outcomes"] for r in rows])
    p_ref = np.repeat([r["p_ref"] for r in rows], [len(r["outcomes"]) for r in rows])
    base = float(y.mean())
    predicted_safe = [r for r in rows if r["p_hat"] == 0.0]
    false_safe = [r for r in predicted_safe if r["p_ref"] > 0]
    bins = {"p̂ = 0": (-0.1, 0.0), "0 < p̂ ≤ 0.5": (0.0, 0.5), "p̂ > 0.5": (0.5, 1.0)}
    reliability = {}
    for name, (a, b) in bins.items():
        m = (p_hat > a) & (p_hat <= b)
        reliability[name] = {
            "n": int(m.sum()),
            "mean_predicted": round(float(p_hat[m].mean()), 3) if m.any() else None,
            "observed": round(float(y[m].mean()), 3) if m.any() else None,
        }
    regrets = [p["decision"][mode]["regret_usd"] for p in points]
    return {
        "branches": len(rows),
        "realisations": int(y.size),
        "brier": round(float(np.mean((p_hat - y) ** 2)), 4),
        "brier_reference_state": round(float(np.mean((p_ref - y) ** 2)), 4),
        "brier_base_rate": round(float(np.mean((base - y) ** 2)), 4),
        "reliability": reliability,
        "predicted_safe_branches": len(predicted_safe),
        "false_safe_branches": len(false_safe),
        "false_safe_mean_true_failure_rate": round(
            float(np.mean([r["p_ref"] for r in false_safe])), 3
        )
        if false_safe
        else None,
        "peak_temperature_p10_p90_coverage": round(
            float(np.mean([r["peak_in_band"] for r in rows])), 3
        ),
        "peak_temperature_median_abs_error_k": round(
            float(np.mean([abs(r["peak_median_error_k"]) for r in rows])), 2
        ),
        "peak_temperature_median_bias_k": round(
            float(np.mean([r["peak_median_error_k"] for r in rows])), 2
        ),
        "decisions": len(regrets),
        "decision_matches_reference_best": sum(
            p["decision"][mode]["chosen"] == p["decision"][mode]["reference_best"] for p in points
        ),
        "decision_regret_mean_usd": round(float(np.mean(regrets)), 1),
        "decision_regret_max_usd": round(float(np.max(regrets)), 1),
    }


def evaluate_counterfactual_calibration(seeds_per_scenario: int = 10, n_jobs: int = -1) -> dict:
    seeds = list(SPLIT_SEEDS["test"])[:seeds_per_scenario]
    jobs = [(sc, sd, mn) for sc in ScenarioId for sd in seeds for mn in DECISION_MINUTES]
    points = [
        p
        for p in Parallel(n_jobs=n_jobs)(delayed(_decision_point)(*j) for j in jobs)
        if p is not None
    ]
    out: dict = {
        "seeds": seeds,
        "decision_minutes": list(DECISION_MINUTES),
        "actions": ["Continue operation", *[describe_action(a) for a in ACTIONS]],
        "members": MEMBERS,
        "horizon_min": HORIZON_MIN,
        "reference": (
            f"Same actions simulated from the hidden true state with {MEMBERS} fresh disturbance "
            f"seeds (base seed {REFERENCE_SEED}); each member is one realisation of the true process."
        ),
        "decision_points": len(points),
        "modes": {},
    }
    for mode in MODES:
        out["modes"][mode] = {
            "overall": _summarise(points, mode),
            "by_scenario": {
                sc.value: _summarise([p for p in points if p["scenario"] == sc.value], mode)
                for sc in ScenarioId
            },
            "by_fault_state": {
                state: _summarise([p for p in points if p["fault_state"] == state], mode)
                for state in FAULT_STATES
            },
            "false_safe_cases": [
                {
                    "case": f"{p['scenario']}/s{p['seed']}@{p['minute']}min",
                    "action": r["action"],
                    "true_failure_rate": r["p_ref"],
                    "fault_onset_min": p["fault_onset_min"],
                    "fault_state": p["fault_state"],
                }
                for p in points
                for r in p["rows"][mode]
                if r["p_hat"] == 0.0 and r["p_ref"] > 0
            ],
        }
    out["points"] = [{k: v for k, v in p.items() if k != "rows"} for p in points]
    return out
