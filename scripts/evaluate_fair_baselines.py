"""Fair Baseline Re-Evaluation across 20 Genuine Fresh Seeds (3000-3019).

Evaluates 5 policies across all 4 scenarios under identical seeds, physics, and disturbances:
1. rule_inspect_on_alarm (Conventional industrial threshold: 130 C or 4.5 mm/s -> inspect immediately)
2. ml_inspect_on_risk (ML-only reactive policy: 60-min risk >= 0.20 -> inspect immediately)
3. orig_det_planner (Deterministic planner without alarm-prioritized dispatch)
4. improved_det_planner (Deterministic planner with alarm-prioritized dispatch)
5. foresight_active (Improved deterministic planner + Information Gate)

Evaluates under both Raw Simulator Accounting and Fair Continuous Shift Accounting,
including terminal alarm penalty sensitivity analysis ($18,000 vs $6,000 vs $0).
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
from joblib import Parallel, delayed

from foresight.artifacts import load_or_train_bundle
from foresight.config import Settings
from foresight.evaluation.interventions import run_policy_episode
from foresight.simulation import DEFAULT_ECONOMICS, ScenarioId

SEEDS = list(range(3000, 3020))  # 20 fresh seeds
SCENARIOS = [
    ScenarioId.HEALTHY,
    ScenarioId.COOLING_DEGRADATION,
    ScenarioId.BEARING_DETERIORATION,
    ScenarioId.OVERLOAD,
]

POLICY_KEYS = [
    "rule_inspect_on_alarm",
    "ml_inspect_on_risk",
    "orig_det_planner",
    "improved_det_planner",
    "foresight_active",
]


def evaluate_single(
    scenario: ScenarioId, seed: int, policy_key: str, bundle, base_settings: Settings
) -> dict:
    if policy_key == "orig_det_planner":
        settings = base_settings.model_copy(update={"alarm_prioritized_dispatch": False})
        ep = run_policy_episode(scenario, seed, "foresight_estimated", bundle, settings)
    elif policy_key == "improved_det_planner":
        settings = base_settings.model_copy(update={"alarm_prioritized_dispatch": True})
        ep = run_policy_episode(scenario, seed, "foresight_estimated", bundle, settings)
    elif policy_key == "foresight_active":
        settings = base_settings.model_copy(update={"alarm_prioritized_dispatch": True})
        ep = run_policy_episode(scenario, seed, "foresight_active", bundle, settings)
    else:
        ep = run_policy_episode(scenario, seed, policy_key, bundle, base_settings)

    # Cost accounting computations
    # ep.cost contains: lost_production, failure_repair, failure_downtime, intervention, deferred_maintenance, terminal_risk_penalty
    raw_breakdown = ep.cost
    raw_total = ep.cost_total

    # Extract residual spilled downtime:
    # If the last intervention was an inspection/bearing repair that extends past 360 min
    spilled_downtime_h = 0.0
    for intv in ep.interventions:
        t_start_min = intv.get("t_min", 0.0)
        act = intv.get("action", {})
        act_type = act.get("type")
        delay_min = act.get("delay_minutes", 0.0)
        eff_start_min = t_start_min + delay_min
        if act_type == "schedule_inspection":
            # In twin.py: inspection downtime = 1.5h (90 min), bearing repair extra = 2.0h (120 min)
            # If scenario is bearing, total downtime = 3.5h (210 min), else 1.5h (90 min)
            dur_min = 210.0 if scenario == ScenarioId.BEARING_DETERIORATION else 90.0
            end_min = eff_start_min + dur_min
            if end_min > 360.0 and eff_start_min < 360.0:
                spilled_downtime_h = max(spilled_downtime_h, (end_min - 360.0) / 60.0)

    spilled_loss = spilled_downtime_h * DEFAULT_ECONOMICS.production_margin_per_hour
    cost_continuous = raw_total + spilled_loss

    # Sensitivity on terminal penalty:
    term_penalty = raw_breakdown.get("terminal_risk_penalty", 0.0)
    base_no_term = raw_total - term_penalty
    cost_term_6k = base_no_term + (6000.0 if term_penalty > 0 else 0.0)
    cost_term_0 = base_no_term

    return {
        "scenario": scenario.value,
        "seed": seed,
        "policy": policy_key,
        "failed": ep.failed,
        "failure_mode": ep.failure_mode,
        "cost_raw": round(raw_total, 2),
        "cost_continuous": round(cost_continuous, 2),
        "cost_term_6k": round(cost_term_6k, 2),
        "cost_term_0": round(cost_term_0, 2),
        "spilled_downtime_h": round(spilled_downtime_h, 3),
        "terminal_penalty": round(term_penalty, 2),
        "breakdown": raw_breakdown,
        "interventions_count": len(ep.interventions),
        "interventions": ep.interventions,
        "peak_temperature_c": round(ep.peak_temperature_c, 2),
        "downtime_h": round(ep.downtime_h, 3),
    }


def main() -> None:
    print("Loading risk models bundle...", flush=True)
    bundle = load_or_train_bundle()
    settings = Settings()

    print(
        f"Starting Fair Baseline Re-Evaluation: {len(SEEDS)} seeds x {len(SCENARIOS)} scenarios x {len(POLICY_KEYS)} policies = {len(SEEDS)*len(SCENARIOS)*len(POLICY_KEYS)} episodes",
        flush=True,
    )
    t0 = time.perf_counter()

    tasks = [
        (sc, sd, pol) for sc in SCENARIOS for sd in SEEDS for pol in POLICY_KEYS
    ]

    results = Parallel(n_jobs=4, batch_size=4)(
        delayed(evaluate_single)(sc, sd, pol, bundle, settings) for sc, sd, pol in tasks
    )

    elapsed = time.perf_counter() - t0
    print(f"All {len(results)} episodes completed in {elapsed:.1f} s ({elapsed/len(results):.2f} s/ep)!", flush=True)

    # Save raw json results
    repo_root = Path(__file__).resolve().parent.parent
    out_dir = repo_root / "artifacts" / "elite_upgrade"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "fair_baseline_reevaluation.json"
    with open(out_file, "w") as f:
        json.dump(
            {
                "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "seeds": SEEDS,
                "scenarios": [s.value for s in SCENARIOS],
                "policies": POLICY_KEYS,
                "elapsed_s": round(elapsed, 1),
                "episodes": results,
            },
            f,
            indent=2,
        )
    print(f"Saved raw results to {out_file}", flush=True)

    # Print summary tables
    print("\n" + "=" * 95)
    print(f"{'POLICY':<24s} | {'RAW MEAN':<10s} | {'RAW MEDIAN':<10s} | {'CONT MEAN':<10s} | {'TERM $6k':<10s} | {'TERM $0':<10s} | {'FAILS':<6s}")
    print("=" * 95)

    for pol in POLICY_KEYS:
        pol_res = [r for r in results if r["policy"] == pol]
        raw_costs = [r["cost_raw"] for r in pol_res]
        cont_costs = [r["cost_continuous"] for r in pol_res]
        t6k_costs = [r["cost_term_6k"] for r in pol_res]
        t0_costs = [r["cost_term_0"] for r in pol_res]
        fails = sum(r["failed"] for r in pol_res)

        print(
            f"{pol:<24s} | "
            f"${np.mean(raw_costs):>8.2f} | "
            f"${np.median(raw_costs):>8.2f} | "
            f"${np.mean(cont_costs):>8.2f} | "
            f"${np.mean(t6k_costs):>8.2f} | "
            f"${np.mean(t0_costs):>8.2f} | "
            f"{fails:>2d}/{len(pol_res)}"
        )
    print("=" * 95)

    print("\nPER-SCENARIO BREAKDOWN (RAW MEAN / CONTINUOUS MEAN):")
    print("-" * 95)
    for sc in SCENARIOS:
        print(f"\nScenario: {sc.value.upper()}")
        for pol in POLICY_KEYS:
            sub = [r for r in results if r["policy"] == pol and r["scenario"] == sc.value]
            raw_c = [r["cost_raw"] for r in sub]
            cont_c = [r["cost_continuous"] for r in sub]
            print(f"  {pol:<24s}: Raw Mean=${np.mean(raw_c):>8.2f} (std={np.std(raw_c):>6.1f}) | Cont Mean=${np.mean(cont_c):>8.2f} | Fails={sum(r['failed'] for r in sub)}")


if __name__ == "__main__":
    main()
