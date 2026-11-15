import json
from pathlib import Path

import numpy as np

p = Path("artifacts/elite_upgrade/fair_baseline_reevaluation.json")
with open(p) as f:
    data = json.load(f)
episodes = data["episodes"]

policies = [
    "rule_inspect_on_alarm",
    "ml_inspect_on_risk",
    "orig_det_planner",
    "improved_det_planner",
    "foresight_active",
]

scenarios = [
    "healthy",
    "cooling_degradation",
    "bearing_deterioration",
    "overload",
]

print("=" * 80)
print(f"EVALUATION SUMMARY ACROSS {len(episodes)} EPISODES (20 SEEDS x 4 SCENARIOS x 5 POLICIES)")
print("=" * 80)

for pol in policies:
    eps = [e for e in episodes if e["policy"] == pol]
    raw_costs = [e["cost_raw"] for e in eps]
    cont_costs = [e["cost_continuous"] for e in eps]
    t6k_costs = [e["cost_term_6k"] for e in eps]
    t0_costs = [e["cost_term_0"] for e in eps]
    spilled = [e["spilled_downtime_h"] for e in eps]
    fails = sum(e["failed"] for e in eps)

    print(f"\nPolicy: {pol} (N={len(eps)})")
    print(f"  • Failures: {fails}/{len(eps)}")
    print(f"  • Raw Cost Mean:        ${np.mean(raw_costs):.2f} (std: ${np.std(raw_costs):.2f}, median: ${np.median(raw_costs):.2f})")
    print(f"  • Continuous Cost Mean: ${np.mean(cont_costs):.2f} (std: ${np.std(cont_costs):.2f}, median: ${np.median(cont_costs):.2f})")
    print(f"  • Mean Spilled Downtime: {np.mean(spilled):.3f} hours (mean spilled cost: ${np.mean(spilled)*600:.2f})")
    print(f"  • Terminal Penalty 6k Mean: ${np.mean(t6k_costs):.2f}")
    print(f"  • Terminal Penalty 0k Mean: ${np.mean(t0_costs):.2f}")

print("\n" + "=" * 80)
print("PER-SCENARIO BREAKDOWN (RAW vs CONTINUOUS)")
print("=" * 80)

for sc in scenarios:
    print(f"\nScenario: {sc}")
    for pol in policies:
        eps = [e for e in episodes if e["policy"] == pol and e["scenario"] == sc]
        raw = np.mean([e["cost_raw"] for e in eps])
        cont = np.mean([e["cost_continuous"] for e in eps])
        spilled_h = np.mean([e["spilled_downtime_h"] for e in eps])
        print(f"  {pol:25s} | Raw: ${raw:8.2f} | Cont: ${cont:8.2f} | Spilled: {spilled_h:.2f}h")

# Paired Differences: Foresight Active vs Improved Deterministic Planner and Rule
print("\n" + "=" * 80)
print("PAIRED COMPARISONS (SEEDS 3000-3019)")
print("=" * 80)

f_eps = [e for e in episodes if e["policy"] == "foresight_active"]
r_eps = [e for e in episodes if e["policy"] == "rule_inspect_on_alarm"]
d_eps = [e for e in episodes if e["policy"] == "improved_det_planner"]

f_raw = np.array([e["cost_raw"] for e in f_eps])
r_raw = np.array([e["cost_raw"] for e in r_eps])
d_raw = np.array([e["cost_raw"] for e in d_eps])

f_cont = np.array([e["cost_continuous"] for e in f_eps])
r_cont = np.array([e["cost_continuous"] for e in r_eps])
d_cont = np.array([e["cost_continuous"] for e in d_eps])

diff_f_minus_d_raw = f_raw - d_raw
diff_f_minus_r_raw = f_raw - r_raw
diff_f_minus_r_cont = f_cont - r_cont

print("Foresight vs Improved Deterministic (Raw):")
print(f"  Mean diff (F - D): ${np.mean(diff_f_minus_d_raw):.2f} (std: ${np.std(diff_f_minus_d_raw):.2f})")
print(f"  95% CI: [${np.mean(diff_f_minus_d_raw) - 1.96*np.std(diff_f_minus_d_raw)/np.sqrt(len(f_raw)):.2f}, ${np.mean(diff_f_minus_d_raw) + 1.96*np.std(diff_f_minus_d_raw)/np.sqrt(len(f_raw)):.2f}]")

print("\nForesight vs Rule (Raw):")
print(f"  Mean diff (F - R): ${np.mean(diff_f_minus_r_raw):.2f} (std: ${np.std(diff_f_minus_r_raw):.2f})")

print("\nForesight vs Rule (Continuous Accounting):")
print(f"  Mean diff (F - R): ${np.mean(diff_f_minus_r_cont):.2f} (std: ${np.std(diff_f_minus_r_cont):.2f})")
print(f"  Rule mean continuous: ${np.mean(r_cont):.2f} vs Foresight mean continuous: ${np.mean(f_cont):.2f}")
