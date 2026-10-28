# Foresight AI — Evaluation Report

Generated: 2026-10-28T15:48:26+00:00 · model bundle `risk-0b8ea03445d0` · git `bc6f468-dirty`

All results come from the simulator (synthetic data). Test episodes use seeds never seen in training or calibration. See *Limitations* at the end.

## 1. Data

| split | episodes | rows | seed range |
|---|---|---|---|
| train | 160 | 46875 | 0–39 |
| validation | 60 | 17841 | 1000–1014 |
| test | 80 | 23281 | 2000–2019 |

## 2. Failure-risk prediction (row level, test split)

### Failure within 15 min — 675 positive of 23281 rows (prevalence 0.029)

| method | precision | recall | F1 | PR-AUC | FPR | Brier | ECE | failures alarmed | median lead (min) | healthy eps alarmed |
|---|---|---|---|---|---|---|---|---|---|---|
| xgboost_calibrated | 0.950 | 0.904 | 0.926 | 0.968 | 0.001 | 0.003 | 0.002 | 45/45 | 14.500 | 0/20 |
| xgboost_raw | 0.954 | 0.898 | 0.925 | 0.974 | 0.001 | 0.003 | 0.002 | 44/45 | 14.200 | 0/20 |
| logistic_regression | 0.850 | 0.892 | 0.871 | 0.942 | 0.005 | 0.006 | 0.003 | 44/45 | 15.000 | 0/20 |
| zscore_max | 0.356 | 0.576 | 0.440 | 0.529 | 0.031 | — | — | 32/45 | 38.200 | 0/20 |
| alarm_threshold_rule | 0.228 | 1.000 | 0.371 | 0.649 | 0.101 | — | — | 45/45 | 31.900 | 0/20 |
| temperature_extrapolation | 0.895 | 0.520 | 0.658 | 0.672 | 0.002 | — | — | 30/45 | 10.500 | 0/20 |

### Failure within 30 min — 1350 positive of 23281 rows (prevalence 0.058)

| method | precision | recall | F1 | PR-AUC | FPR | Brier | ECE | failures alarmed | median lead (min) | healthy eps alarmed |
|---|---|---|---|---|---|---|---|---|---|---|
| xgboost_calibrated | 0.915 | 0.892 | 0.903 | 0.949 | 0.005 | 0.009 | 0.006 | 44/45 | 29.700 | 0/20 |
| xgboost_raw | 0.919 | 0.889 | 0.904 | 0.960 | 0.005 | 0.008 | 0.004 | 44/45 | 29.700 | 0/20 |
| logistic_regression | 0.855 | 0.902 | 0.878 | 0.949 | 0.009 | 0.010 | 0.003 | 45/45 | 29.500 | 0/20 |
| zscore_max | 0.488 | 0.762 | 0.595 | 0.691 | 0.049 | — | — | 42/45 | 45.400 | 0/20 |
| alarm_threshold_rule | 0.426 | 0.935 | 0.585 | 0.649 | 0.078 | — | — | 45/45 | 31.900 | 0/20 |
| temperature_extrapolation | 0.726 | 0.524 | 0.608 | 0.672 | 0.012 | — | — | 30/45 | 21.800 | 0/20 |

### Failure within 60 min — 2700 positive of 23281 rows (prevalence 0.116)

| method | precision | recall | F1 | PR-AUC | FPR | Brier | ECE | failures alarmed | median lead (min) | healthy eps alarmed |
|---|---|---|---|---|---|---|---|---|---|---|
| xgboost_calibrated | 0.894 | 0.835 | 0.864 | 0.935 | 0.013 | 0.023 | 0.011 | 45/45 | 54.800 | 0/20 |
| xgboost_raw | 0.892 | 0.840 | 0.865 | 0.941 | 0.013 | 0.024 | 0.014 | 45/45 | 54.900 | 0/20 |
| logistic_regression | 0.798 | 0.872 | 0.833 | 0.922 | 0.029 | 0.028 | 0.008 | 45/45 | 55.800 | 0/20 |
| zscore_max | 0.689 | 0.693 | 0.691 | 0.774 | 0.041 | — | — | 44/45 | 50.400 | 0/20 |
| alarm_threshold_rule | 0.556 | 0.610 | 0.582 | 0.602 | 0.064 | — | — | 45/45 | 31.900 | 0/20 |
| temperature_extrapolation | 0.653 | 0.473 | 0.549 | 0.684 | 0.033 | — | — | 30/45 | 40.000 | 0/20 |

Methods:
- `xgboost_calibrated`: Gradient-boosted trees on 16 causal features, isotonic-calibrated on validation.
- `xgboost_raw`: Same model before calibration.
- `logistic_regression`: Supervised linear baseline (standardised features).
- `zscore_max`: Statistical baseline: max |z| vs healthy training data; threshold tuned on validation.
- `alarm_threshold_rule`: Conventional alarm: winding ≥ 130 °C or vibration ≥ 4.5 mm/s (no tuning).
- `temperature_extrapolation`: Heuristic: linear 30-min temperature trend reaches 155 °C within the horizon.

## 3. Anomaly and change-point detection

| detector | detected | missed | median delay (min) | p90 delay | pre-onset alarms | healthy eps alarmed |
|---|---|---|---|---|---|---|
| isolation_forest | 54/60 | 6 | 27.000 | 107.000 | 0 | 0/20 |
| cusum_any | 60/60 | 0 | 12.800 | 43.100 | 1 | 3/20 |

Fault onset is the scripted initiation time; many faults are physically invisible for some time after onset, so detection delay includes the latent period.

## 4. Fault diagnosis

| subset | rows | accuracy | macro F1 |
|---|---|---|---|
| all_rows | 23281 | 0.975 | 0.972 |
| rows_30min_after_onset_or_healthy | 21481 | 0.996 | 0.995 |

Classes: none, cooling, bearing, overload. Rows labelled with a fault right after onset are often not yet observable.

Inference latency: p50 53.39 ms, p95 113.72 ms (3 calibrated horizons + isolation forest + diagnosis for one feature row, CPU).

## 5. Closed-loop intervention outcomes

4 scenarios × 5 held-out seeds × 6 h per episode. Recommended actions were auto-approved by the harness (simulation only).

| policy | failures | 95% CI | mean cost ($) | Δ cost vs none | downtime (h) | interventions | healthy eps touched |
|---|---|---|---|---|---|---|---|
| no_action | 10/20 | 0.30–0.70 | 16835.100 | — | 0.004 | 0.000 | 0 |
| rule_derate | 0/20 | 0.00–0.16 | 3210.700 | -13624.400 | 0.463 | 1.000 | 0 |
| rule_shutdown_on_alarm | 0/20 | 0.00–0.16 | 2899.400 | -13935.700 | 1.696 | 0.700 | 0 |
| rule_inspect_on_alarm | 0/20 | 0.00–0.16 | 1472.500 | -15362.600 | 1.084 | 0.700 | 0 |
| foresight_estimated | 0/20 | 0.00–0.16 | 1760.000 | -15075.100 | 1.637 | 0.950 | 0 |
| foresight_oracle | 0/20 | 0.00–0.16 | 1464.500 | -15370.600 | 1.604 | 0.700 | 0 |

Failures by scenario:

| policy | healthy | cooling_degradation | bearing_deterioration | overload |
|---|---|---|---|---|
| no_action | 0/5 | 4/5 | 3/5 | 3/5 |
| rule_derate | 0/5 | 0/5 | 0/5 | 0/5 |
| rule_shutdown_on_alarm | 0/5 | 0/5 | 0/5 | 0/5 |
| rule_inspect_on_alarm | 0/5 | 0/5 | 0/5 | 0/5 |
| foresight_estimated | 0/5 | 0/5 | 0/5 | 0/5 |
| foresight_oracle | 0/5 | 0/5 | 0/5 | 0/5 |

Mean cost by scenario ($):

| policy | healthy | cooling_degradation | bearing_deterioration | overload |
|---|---|---|---|---|
| no_action | 0.000 | 20504.900 | 23880.000 | 22955.500 |
| rule_derate | 0.000 | 6019.900 | 4674.400 | 2148.700 |
| rule_shutdown_on_alarm | 0.000 | 2821.400 | 5082.000 | 3694.200 |
| rule_inspect_on_alarm | 0.000 | 1554.000 | 2782.000 | 1554.000 |
| foresight_estimated | 0.000 | 1724.000 | 3480.000 | 1836.000 |
| foresight_oracle | 0.000 | 1534.000 | 2770.000 | 1554.000 |

Policies:
- `no_action`: Never intervene.
- `rule_derate`: Alarm (≥130 °C or ≥4.5 mm/s) → reduce load 30 %; ≥145 °C or ≥6.5 mm/s → shutdown.
- `rule_shutdown_on_alarm`: Alarm → controlled shutdown (stays down; fault left for later repair).
- `rule_inspect_on_alarm`: Alarm → immediate inspection (strong maintenance-aware rule).
- `foresight_estimated`: Risk-triggered agent (deterministic planner) → Future Branching from the telemetry-estimated state → verifier → auto-approved action.
- `foresight_oracle`: Same loop, but branches simulate the hidden true state (upper bound).

## 6. Agent reliability

| provider | runs | completed | recommended | tool success | invalid actions | verifier rejections | latency p50/p95 (ms) | cost ($) |
|---|---|---|---|---|---|---|---|---|
| deterministic-planner | 118 | 1.000 | 0.280 | 1.000 | 0 | 10 | 7564.600/18682.700 | 0.000 |

Live model comparison: 6 arms × 7 cases × 3 repeats = 126 runs, total estimated cost $5.65. Cases: cooling_degradation@100min/s7, cooling_degradation@100min/s2011, bearing_deterioration@120min/s7, bearing_deterioration@120min/s2011, overload@60min/s7, overload@60min/s2011, healthy@100min/s7.
Generated 2026-10-28T02:27:46+00:00 · git `4ab6cb0-dirty`.
Verifier: v2 (before the vibration-margin and strict-improvement fixes).

| arm | model | runs | completed | mean regret $ (95% CI) | worse / better | unsafe choice | healthy false alarm | rejections | fallbacks | halluc. ids | p50/p95 latency (s) | cost $ / run |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| meta:low | muse-spark-1.3 | 21 | 1.000 | 3.300 [-57.1, 91.0] | 1 / 4 | 0/21 (CI 0.00–0.15) | 0/3 (CI 0.00–0.56) | 2 | 6 | 0 | 70.2/117.4 | 0.0409 |
| meta:medium | muse-spark-1.3 | 21 | 1.000 | -3.800 [-66.7, 83.8] | 1 / 4 | 0/21 (CI 0.00–0.15) | 0/3 (CI 0.00–0.56) | 1 | 4 | 0 | 88.5/151.1 | 0.0544 |
| meta:high | muse-spark-1.3 | 21 | 1.000 | -21.400 [-50.0, 0.0] | 0 / 3 | 0/21 (CI 0.00–0.15) | 0/3 (CI 0.00–0.56) | 0 | 4 | 0 | 98.6/163.8 | 0.0642 |
| fireworks:low | muse-spark-open | 21 | 0.905 | 328.400 [40.0, 664.2] | 6 / 5 | 0/19 (CI 0.00–0.17) | 0/3 (CI 0.00–0.56) | 0 | 0 | 0 | 87.4/300.0 | 0.0241 |
| fireworks:medium | muse-spark-open | 21 | 1.000 | 130.500 [-35.7, 364.8] | 3 / 5 | 0/21 (CI 0.00–0.15) | 0/3 (CI 0.00–0.56) | 1 | 0 | 0 | 119.4/255.9 | 0.0354 |
| fireworks:high | muse-spark-open | 21 | 0.952 | 121.000 [-70.0, 377.0] | 3 / 6 | 0/20 (CI 0.00–0.16) | 0/3 (CI 0.00–0.56) | 0 | 0 | 0 | 175.1/299.4 | 0.0502 |

Regret: agent branch objective minus planner branch objective in one shared audit comparison (16 members, seed 777, 180-min horizon; positive means the agent's choice is worse under the simulator's cost model). Mean-regret CIs are percentile bootstrap; rate CIs are Wilson 95%. 'Unsafe choice' = the recommended action still shows failures in the audit ensemble. Per-run detail is in `evaluation.json`.

### Re-check after verifier fixes

Live model comparison: 2 arms × 7 cases × 2 repeats = 28 runs, total estimated cost $1.64. Cases: cooling_degradation@100min/s7, cooling_degradation@100min/s2011, bearing_deterioration@120min/s7, bearing_deterioration@120min/s2011, overload@60min/s7, overload@60min/s2011, healthy@100min/s7.
Generated 2026-10-28T16:10:45+00:00 · git `bc6f468-dirty`.
Verifier: v3 (vibration margin, strict improvement, horizon; v4 not yet re-checked).

| arm | model | runs | completed | mean regret $ (95% CI) | worse / better | unsafe choice | healthy false alarm | rejections | fallbacks | halluc. ids | p50/p95 latency (s) | cost $ / run |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| meta:high | muse-spark-1.3 | 14 | 1.000 | 0.700 [-100.0, 145.0] | 1 / 4 | 0/14 (CI 0.00–0.21) | 0/2 (CI 0.00–0.66) | 2 | 2 | 0 | 98.3/181.5 | 0.0624 |
| fireworks:high | muse-spark-open | 14 | 1.000 | 45.700 [-85.7, 214.3] | 2 / 4 | 0/14 (CI 0.00–0.21) | 0/2 (CI 0.00–0.66) | 0 | 0 | 0 | 192.7/293.1 | 0.0548 |

Regret: agent branch objective minus planner branch objective in one shared audit comparison (16 members, seed 777, 180-min horizon; positive means the agent's choice is worse under the simulator's cost model). Mean-regret CIs are percentile bootstrap; rate CIs are Wilson 95%. 'Unsafe choice' = the recommended action still shows failures in the audit ensemble. Per-run detail is in `evaluation.json`.

## 7. Limitations

- All data is synthetic, produced by the project's own digital twin; the twin's physics and fault models are simplified (lumped thermal node, parametric bearing damage growth).
- The predictive models are trained and tested on the same simulator family, so test results measure generalisation across randomized episodes, not transfer to real machines.
- Intervention outcomes depend on illustrative economic parameters (simulation/params.py).
- In the closed-loop evaluation, approvals are auto-granted by the harness; the live system requires explicit human approval.
- The closed-loop agent is the deterministic planner; live model runs (Meta Model API and Fireworks AI) are reported separately as single-decision snapshots, not closed-loop episodes. The planner, the verifier, and the regret audit share the same simulator.
- Sample sizes are small (a handful of episodes per scenario), so confidence intervals are wide.
