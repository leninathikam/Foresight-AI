# Foresight AI — Evaluation Report

Generated: 2026-10-29T19:11:47+00:00 · model bundle `risk-0b8ea03445d0` · git `8c3d04a-dirty`

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

Inference latency: p50 32.08 ms, p95 40.87 ms (3 calibrated horizons + isolation forest + diagnosis for one feature row, CPU).

## 5. Closed-loop intervention outcomes

4 scenarios × 5 held-out seeds (2000–2004) × 6 h per episode. Recommended actions were auto-approved by the harness (simulation only).

| policy | failures | 95% CI | mean cost ($) | Δ cost vs none | downtime (h) | interventions | healthy eps touched |
|---|---|---|---|---|---|---|---|
| no_action | 10/20 | 0.30–0.70 | 16835.100 | — | 0.004 | 0.000 | 0 |
| rule_derate | 0/20 | 0.00–0.16 | 3210.700 | -13624.400 | 0.463 | 1.000 | 0 |
| rule_shutdown_on_alarm | 0/20 | 0.00–0.16 | 2899.400 | -13935.700 | 1.696 | 0.700 | 0 |
| rule_inspect_on_alarm | 0/20 | 0.00–0.16 | 1472.500 | -15362.600 | 1.084 | 0.700 | 0 |
| ml_inspect_on_risk | 0/20 | 0.00–0.16 | 2754.000 | -14081.100 | 2.442 | 1.800 | 0 |
| foresight_estimated | 0/20 | 0.00–0.16 | 1765.000 | -15070.100 | 1.646 | 0.950 | 0 |
| foresight_active | 0/20 | 0.00–0.16 | 1647.000 | -15188.100 | 1.542 | 0.800 | 0 |
| foresight_oracle | 0/20 | 0.00–0.16 | 1469.500 | -15365.600 | 1.613 | 0.700 | 0 |

Failures by scenario:

| policy | healthy | cooling_degradation | bearing_deterioration | overload |
|---|---|---|---|---|
| no_action | 0/5 | 4/5 | 3/5 | 3/5 |
| rule_derate | 0/5 | 0/5 | 0/5 | 0/5 |
| rule_shutdown_on_alarm | 0/5 | 0/5 | 0/5 | 0/5 |
| rule_inspect_on_alarm | 0/5 | 0/5 | 0/5 | 0/5 |
| ml_inspect_on_risk | 0/5 | 0/5 | 0/5 | 0/5 |
| foresight_estimated | 0/5 | 0/5 | 0/5 | 0/5 |
| foresight_active | 0/5 | 0/5 | 0/5 | 0/5 |
| foresight_oracle | 0/5 | 0/5 | 0/5 | 0/5 |

Mean cost by scenario ($):

| policy | healthy | cooling_degradation | bearing_deterioration | overload |
|---|---|---|---|---|
| no_action | 0.000 | 20504.900 | 23880.000 | 22955.500 |
| rule_derate | 0.000 | 6019.900 | 4674.400 | 2148.700 |
| rule_shutdown_on_alarm | 0.000 | 2821.400 | 5082.000 | 3694.200 |
| rule_inspect_on_alarm | 0.000 | 1554.000 | 2782.000 | 1554.000 |
| ml_inspect_on_risk | 0.000 | 2652.000 | 4120.000 | 4244.000 |
| foresight_estimated | 0.000 | 1744.000 | 3480.000 | 1836.000 |
| foresight_active | 0.000 | 1554.000 | 3480.000 | 1554.000 |
| foresight_oracle | 0.000 | 1554.000 | 2770.000 | 1554.000 |

Policies:
- `no_action`: Never intervene.
- `rule_derate`: Alarm (≥130 °C or ≥4.5 mm/s) → reduce load 30 %; ≥145 °C or ≥6.5 mm/s → shutdown.
- `rule_shutdown_on_alarm`: Alarm → controlled shutdown (stays down; fault left for later repair).
- `rule_inspect_on_alarm`: Alarm → immediate inspection (strong maintenance-aware rule).
- `ml_inspect_on_risk`: Foresight's own trigger (calibrated 60-min risk ≥ 0.2, anomaly or hard alarm; same cadence, cooldown and cap) → immediate inspection, with no simulation or verifier. Isolates what Future Branching adds over the ML risk model.
- `foresight_estimated`: Agent woken by risk, anomaly or hard alarm (deterministic planner) → Future Branching from the telemetry-estimated state → verifier → auto-approved action. No information gate.
- `foresight_active`: foresight_estimated plus the information gate: a verified action is held back while its risk rests on statistically unsupported trends and waiting is safe.
- `foresight_oracle`: Same loop, but branches simulate the hidden true state (upper bound).

### 5.1 Confirmation on further test seeds

Same policies on the next 10 test seeds. They were clean for the information gate, but the alarm trigger and immediate-inspection candidates were added after inspecting them (an episode where the hard alarm fired 8 min before the end and Foresight never woke up).

4 scenarios × 10 held-out seeds (2005–2014) × 6 h per episode. Recommended actions were auto-approved by the harness (simulation only).

| policy | failures | 95% CI | mean cost ($) | Δ cost vs none | downtime (h) | interventions | healthy eps touched |
|---|---|---|---|---|---|---|---|
| no_action | 25/40 | 0.47–0.76 | 17475.400 | — | 0.005 | 0.000 | 0 |
| rule_derate | 0/40 | 0.00–0.09 | 3723.700 | -13751.700 | 0.437 | 1.020 | 0 |
| rule_shutdown_on_alarm | 0/40 | 0.00–0.09 | 2976.800 | -14498.600 | 1.809 | 0.700 | 0 |
| rule_inspect_on_alarm | 0/40 | 0.00–0.09 | 1595.000 | -15880.400 | 1.113 | 0.700 | 0 |
| ml_inspect_on_risk | 0/40 | 0.00–0.09 | 2842.200 | -14633.200 | 2.492 | 1.800 | 0 |
| foresight_estimated | 0/40 | 0.00–0.09 | 2333.900 | -15141.500 | 1.658 | 0.950 | 0 |
| foresight_active | 0/40 | 0.00–0.09 | 2295.900 | -15179.500 | 1.644 | 0.900 | 0 |
| foresight_oracle | 0/40 | 0.00–0.09 | 2160.000 | -15315.400 | 1.342 | 0.750 | 0 |

Failures by scenario:

| policy | healthy | cooling_degradation | bearing_deterioration | overload |
|---|---|---|---|---|
| no_action | 0/10 | 8/10 | 8/10 | 9/10 |
| rule_derate | 0/10 | 0/10 | 0/10 | 0/10 |
| rule_shutdown_on_alarm | 0/10 | 0/10 | 0/10 | 0/10 |
| rule_inspect_on_alarm | 0/10 | 0/10 | 0/10 | 0/10 |
| ml_inspect_on_risk | 0/10 | 0/10 | 0/10 | 0/10 |
| foresight_estimated | 0/10 | 0/10 | 0/10 | 0/10 |
| foresight_active | 0/10 | 0/10 | 0/10 | 0/10 |
| foresight_oracle | 0/10 | 0/10 | 0/10 | 0/10 |

Mean cost by scenario ($):

| policy | healthy | cooling_degradation | bearing_deterioration | overload |
|---|---|---|---|---|
| no_action | 144.000 | 24084.800 | 20976.000 | 24696.800 |
| rule_derate | 144.000 | 6123.700 | 6447.900 | 2179.300 |
| rule_shutdown_on_alarm | 144.000 | 2961.000 | 5090.000 | 3712.400 |
| rule_inspect_on_alarm | 144.000 | 1405.000 | 3250.000 | 1581.000 |
| ml_inspect_on_risk | 144.000 | 2890.000 | 4175.500 | 4159.500 |
| foresight_estimated | 144.000 | 3544.000 | 3626.500 | 2021.000 |
| foresight_active | 144.000 | 3457.000 | 3626.500 | 1956.000 |
| foresight_oracle | 144.000 | 3277.000 | 3638.000 | 1581.000 |

### 5.2 Final hold-out seeds

Same policies on the last test seeds, never inspected during development: the clean check of every change, including the alarm trigger and immediate-inspection candidates.

4 scenarios × 5 held-out seeds (2015–2019) × 6 h per episode. Recommended actions were auto-approved by the harness (simulation only).

| policy | failures | 95% CI | mean cost ($) | Δ cost vs none | downtime (h) | interventions | healthy eps touched |
|---|---|---|---|---|---|---|---|
| no_action | 10/20 | 0.30–0.70 | 16757.000 | — | 0.003 | 0.000 | 0 |
| rule_derate | 0/20 | 0.00–0.16 | 4979.400 | -11777.500 | 0.357 | 0.900 | 0 |
| rule_shutdown_on_alarm | 0/20 | 0.00–0.16 | 2912.300 | -13844.600 | 1.648 | 0.700 | 0 |
| rule_inspect_on_alarm | 0/20 | 0.00–0.16 | 1498.000 | -15259.000 | 0.966 | 0.700 | 0 |
| ml_inspect_on_risk | 0/20 | 0.00–0.16 | 2762.000 | -13995.000 | 2.375 | 1.850 | 0 |
| foresight_estimated | 0/20 | 0.00–0.16 | 2722.000 | -14035.000 | 1.596 | 0.950 | 0 |
| foresight_active | 0/20 | 0.00–0.16 | 2645.200 | -14111.700 | 1.517 | 0.900 | 0 |
| foresight_oracle | 0/20 | 0.00–0.16 | 2421.000 | -14336.000 | 1.521 | 0.750 | 0 |

Failures by scenario:

| policy | healthy | cooling_degradation | bearing_deterioration | overload |
|---|---|---|---|---|
| no_action | 0/5 | 3/5 | 4/5 | 3/5 |
| rule_derate | 0/5 | 0/5 | 0/5 | 0/5 |
| rule_shutdown_on_alarm | 0/5 | 0/5 | 0/5 | 0/5 |
| rule_inspect_on_alarm | 0/5 | 0/5 | 0/5 | 0/5 |
| ml_inspect_on_risk | 0/5 | 0/5 | 0/5 | 0/5 |
| foresight_estimated | 0/5 | 0/5 | 0/5 | 0/5 |
| foresight_active | 0/5 | 0/5 | 0/5 | 0/5 |
| foresight_oracle | 0/5 | 0/5 | 0/5 | 0/5 |

Mean cost by scenario ($):

| policy | healthy | cooling_degradation | bearing_deterioration | overload |
|---|---|---|---|---|
| no_action | 144.000 | 22920.000 | 21004.400 | 22959.500 |
| rule_derate | 144.000 | 2467.600 | 15149.700 | 2156.300 |
| rule_shutdown_on_alarm | 144.000 | 2864.000 | 4921.800 | 3719.600 |
| rule_inspect_on_alarm | 144.000 | 1212.000 | 3081.800 | 1554.000 |
| ml_inspect_on_risk | 144.000 | 2380.000 | 4348.000 | 4176.000 |
| foresight_estimated | 144.000 | 4960.000 | 3630.000 | 2154.000 |
| foresight_active | 144.000 | 4960.000 | 3623.000 | 1854.000 |
| foresight_oracle | 144.000 | 4960.000 | 3026.000 | 1554.000 |

## 6. Counterfactual calibration

116 held-out decision points (seeds 2000–2009, minutes 60, 120, 180, no intervention applied yet). At each point the planner's estimated-state ensemble (16 members, 180-min horizon) predicts the outcome of each action (Continue operation, Reduce load by 30%, Auxiliary cooling +40% airflow, Inspection in 10 min). Reference: Same actions simulated from the hidden true state with 16 fresh disturbance seeds (base seed 500); each member is one realisation of the true process.

`fixed` is the trend spread the planner and verifier use; `standard_error` widens each trend's spread to the standard error of its fit (used by the information gate's safety-of-waiting check).

| uncertainty model | branches | Brier | Brier (true state) | Brier (base rate) | predicted safe → true failures | peak-T p10–p90 coverage | peak-T median |error| (K) | objective-best action = true best | decision regret mean / max ($) |
|---|---|---|---|---|---|---|---|---|---|
| fixed | 464 | 0.099 | 0.001 | 0.134 | 26/382 | 0.250 | 6.830 | 71/116 | 5424.4 / 23773.6 |
| standard_error | 464 | 0.099 | 0.001 | 0.134 | 26/380 | 0.279 | 6.850 | 68/116 | 5246.9 / 23806.3 |

By scenario (`fixed`):

| scenario | Brier | predicted safe → true failures | peak-T coverage | peak-T bias (K) | decision regret mean ($) |
|---|---|---|---|---|---|
| healthy | 0.000 | 0/120 | 0.128 | 1.170 | 0.800 |
| cooling_degradation | 0.104 | 9/87 | 0.358 | -8.940 | 6957.500 |
| bearing_deterioration | 0.096 | 9/99 | 0.299 | -0.880 | 6286.400 |
| overload | 0.205 | 8/76 | 0.212 | -5.390 | 8821.400 |

By fault state at the decision point (`fixed`). *Latent* means the fault is scheduled but has not started, so no telemetry can reveal it yet; *active* is the fair test of the estimator:

| fault state | decision points | Brier | predicted safe → true failures | peak-T coverage | peak-T median |error| (K) | decision regret mean ($) |
|---|---|---|---|---|---|---|
| no_fault | 30 | 0.000 | 0/120 | 0.128 | 1.260 | 0.800 |
| latent | 32 | 0.148 | 19/128 | 0.098 | 14.720 | 14955.800 |
| active | 54 | 0.124 | 7/134 | 0.408 | 5.260 | 2789.400 |

Predicted-safe branches that fail in the true process (`fixed`):

- cooling_degradation/s2001@60min · Continue operation · true failure rate 1.00 · fault latent (onset 98 min)
- cooling_degradation/s2003@120min · Continue operation · true failure rate 1.00 · fault latent (onset 140 min)
- cooling_degradation/s2003@120min · Auxiliary cooling +40% airflow · true failure rate 1.00 · fault latent (onset 140 min)
- cooling_degradation/s2004@120min · Continue operation · true failure rate 1.00 · fault active (onset 114 min)
- cooling_degradation/s2004@120min · Auxiliary cooling +40% airflow · true failure rate 1.00 · fault active (onset 114 min)
- cooling_degradation/s2005@120min · Continue operation · true failure rate 1.00 · fault latent (onset 131 min)
- cooling_degradation/s2005@120min · Auxiliary cooling +40% airflow · true failure rate 1.00 · fault latent (onset 131 min)
- cooling_degradation/s2007@60min · Continue operation · true failure rate 1.00 · fault latent (onset 83 min)
- cooling_degradation/s2007@60min · Auxiliary cooling +40% airflow · true failure rate 1.00 · fault latent (onset 83 min)
- bearing_deterioration/s2000@120min · Continue operation · true failure rate 1.00 · fault active (onset 50 min)
- bearing_deterioration/s2001@60min · Continue operation · true failure rate 1.00 · fault latent (onset 80 min)
- bearing_deterioration/s2001@60min · Auxiliary cooling +40% airflow · true failure rate 1.00 · fault latent (onset 80 min)
- bearing_deterioration/s2004@120min · Continue operation · true failure rate 1.00 · fault active (onset 91 min)
- bearing_deterioration/s2004@120min · Auxiliary cooling +40% airflow · true failure rate 1.00 · fault active (onset 91 min)
- bearing_deterioration/s2008@120min · Continue operation · true failure rate 1.00 · fault active (onset 105 min)
- bearing_deterioration/s2009@60min · Continue operation · true failure rate 1.00 · fault latent (onset 125 min)
- bearing_deterioration/s2009@120min · Continue operation · true failure rate 1.00 · fault latent (onset 125 min)
- bearing_deterioration/s2009@120min · Auxiliary cooling +40% airflow · true failure rate 1.00 · fault latent (onset 125 min)
- overload/s2000@60min · Continue operation · true failure rate 1.00 · fault active (onset 58 min)
- overload/s2002@60min · Continue operation · true failure rate 1.00 · fault latent (onset 74 min)
- overload/s2004@60min · Continue operation · true failure rate 1.00 · fault latent (onset 97 min)
- overload/s2007@60min · Continue operation · true failure rate 1.00 · fault latent (onset 134 min)
- overload/s2007@120min · Continue operation · true failure rate 1.00 · fault latent (onset 134 min)
- overload/s2008@60min · Continue operation · true failure rate 1.00 · fault latent (onset 100 min)
- overload/s2009@60min · Continue operation · true failure rate 1.00 · fault latent (onset 131 min)
- overload/s2009@120min · Continue operation · true failure rate 1.00 · fault latent (onset 131 min)

Predicted-safe branches that fail in the true process (`standard_error`):

- cooling_degradation/s2001@60min · Continue operation · true failure rate 1.00 · fault latent (onset 98 min)
- cooling_degradation/s2003@120min · Continue operation · true failure rate 1.00 · fault latent (onset 140 min)
- cooling_degradation/s2003@120min · Auxiliary cooling +40% airflow · true failure rate 1.00 · fault latent (onset 140 min)
- cooling_degradation/s2004@120min · Continue operation · true failure rate 1.00 · fault active (onset 114 min)
- cooling_degradation/s2004@120min · Auxiliary cooling +40% airflow · true failure rate 1.00 · fault active (onset 114 min)
- cooling_degradation/s2005@120min · Continue operation · true failure rate 1.00 · fault latent (onset 131 min)
- cooling_degradation/s2005@120min · Auxiliary cooling +40% airflow · true failure rate 1.00 · fault latent (onset 131 min)
- cooling_degradation/s2007@60min · Continue operation · true failure rate 1.00 · fault latent (onset 83 min)
- cooling_degradation/s2007@60min · Auxiliary cooling +40% airflow · true failure rate 1.00 · fault latent (onset 83 min)
- bearing_deterioration/s2000@120min · Continue operation · true failure rate 1.00 · fault active (onset 50 min)
- bearing_deterioration/s2001@60min · Continue operation · true failure rate 1.00 · fault latent (onset 80 min)
- bearing_deterioration/s2001@60min · Auxiliary cooling +40% airflow · true failure rate 1.00 · fault latent (onset 80 min)
- bearing_deterioration/s2004@120min · Continue operation · true failure rate 1.00 · fault active (onset 91 min)
- bearing_deterioration/s2004@120min · Auxiliary cooling +40% airflow · true failure rate 1.00 · fault active (onset 91 min)
- bearing_deterioration/s2008@120min · Continue operation · true failure rate 1.00 · fault active (onset 105 min)
- bearing_deterioration/s2009@60min · Continue operation · true failure rate 1.00 · fault latent (onset 125 min)
- bearing_deterioration/s2009@120min · Continue operation · true failure rate 1.00 · fault latent (onset 125 min)
- bearing_deterioration/s2009@120min · Auxiliary cooling +40% airflow · true failure rate 1.00 · fault latent (onset 125 min)
- overload/s2000@60min · Continue operation · true failure rate 1.00 · fault active (onset 58 min)
- overload/s2002@60min · Continue operation · true failure rate 1.00 · fault latent (onset 74 min)
- overload/s2004@60min · Continue operation · true failure rate 1.00 · fault latent (onset 97 min)
- overload/s2007@60min · Continue operation · true failure rate 1.00 · fault latent (onset 134 min)
- overload/s2007@120min · Continue operation · true failure rate 1.00 · fault latent (onset 134 min)
- overload/s2008@60min · Continue operation · true failure rate 1.00 · fault latent (onset 100 min)
- overload/s2009@60min · Continue operation · true failure rate 1.00 · fault latent (onset 131 min)
- overload/s2009@120min · Continue operation · true failure rate 1.00 · fault latent (onset 131 min)

'Predicted safe → true failures' counts branches where the estimated ensemble shows no failure (what the verifier's failure_risk check requires) but some true-process realisations fail. The Brier score is computed against every true-process realisation; 'true state' is the irreducible score of a predictor that knows the hidden state. Peak-T coverage is the share of true realisations whose peak winding temperature falls inside the ensemble's 10–90 % band (nominal 0.8). Decision regret prices the estimated ensemble's lowest-objective action under the true-state reference (not verifier-gated).

## 7. Agent reliability

| provider | runs | completed | recommended | tool success | invalid actions | verifier rejections | latency p50/p95 (ms) | cost ($) |
|---|---|---|---|---|---|---|---|---|
| deterministic-planner | 182 | 1.000 | 0.269 | 1.000 | 0 | 15 | 11988.800/27745.700 | 0.000 |

Live model comparison: 6 arms × 7 cases × 3 repeats = 126 runs, total estimated cost $5.65. Cases: cooling_degradation@100min/s7, cooling_degradation@100min/s2011, bearing_deterioration@120min/s7, bearing_deterioration@120min/s2011, overload@60min/s7, overload@60min/s2011, healthy@100min/s7.
Generated 2026-10-28T02:27:46+00:00 · git `4ab6cb0-dirty`.
Verifier: v2 (before the vibration-margin and strict-improvement fixes).

| arm | model | runs | completed | mean regret $ (95% CI) | worse / better | unsafe choice | healthy false alarm | held for data | rejections | fallbacks | halluc. ids | p50/p95 latency (s) | cost $ / run |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| meta:low | muse-spark-1.3 | 21 | 1.000 | 3.300 [-57.1, 91.0] | 1 / 4 | 0/21 (CI 0.00–0.15) | 0/3 (CI 0.00–0.56) | — | 2 | 6 | 0 | 70.2/117.4 | 0.0409 |
| meta:medium | muse-spark-1.3 | 21 | 1.000 | -3.800 [-66.7, 83.8] | 1 / 4 | 0/21 (CI 0.00–0.15) | 0/3 (CI 0.00–0.56) | — | 1 | 4 | 0 | 88.5/151.1 | 0.0544 |
| meta:high | muse-spark-1.3 | 21 | 1.000 | -21.400 [-50.0, 0.0] | 0 / 3 | 0/21 (CI 0.00–0.15) | 0/3 (CI 0.00–0.56) | — | 0 | 4 | 0 | 98.6/163.8 | 0.0642 |
| fireworks:low | muse-spark-open | 21 | 0.905 | 328.400 [40.0, 664.2] | 6 / 5 | 0/19 (CI 0.00–0.17) | 0/3 (CI 0.00–0.56) | — | 0 | 0 | 0 | 87.4/300.0 | 0.0241 |
| fireworks:medium | muse-spark-open | 21 | 1.000 | 130.500 [-35.7, 364.8] | 3 / 5 | 0/21 (CI 0.00–0.15) | 0/3 (CI 0.00–0.56) | — | 1 | 0 | 0 | 119.4/255.9 | 0.0354 |
| fireworks:high | muse-spark-open | 21 | 0.952 | 121.000 [-70.0, 377.0] | 3 / 6 | 0/20 (CI 0.00–0.16) | 0/3 (CI 0.00–0.56) | — | 0 | 0 | 0 | 175.1/299.4 | 0.0502 |

Regret: agent branch objective minus planner branch objective in one shared audit comparison (16 members, seed 777, 180-min horizon; positive means the agent's choice is worse under the simulator's cost model). Mean-regret CIs are percentile bootstrap; rate CIs are Wilson 95%. 'Unsafe choice' = the recommended action still shows failures in the audit ensemble. Per-run detail is in `evaluation.json`.

### Re-check after verifier fixes

Live model comparison: 2 arms × 7 cases × 2 repeats = 28 runs, total estimated cost $1.64. Cases: cooling_degradation@100min/s7, cooling_degradation@100min/s2011, bearing_deterioration@120min/s7, bearing_deterioration@120min/s2011, overload@60min/s7, overload@60min/s2011, healthy@100min/s7.
Generated 2026-10-28T16:10:45+00:00 · git `bc6f468-dirty`.
Verifier: v3 (vibration margin, strict improvement, horizon; v4 not yet re-checked).

| arm | model | runs | completed | mean regret $ (95% CI) | worse / better | unsafe choice | healthy false alarm | held for data | rejections | fallbacks | halluc. ids | p50/p95 latency (s) | cost $ / run |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| meta:high | muse-spark-1.3 | 14 | 1.000 | 0.700 [-100.0, 145.0] | 1 / 4 | 0/14 (CI 0.00–0.21) | 0/2 (CI 0.00–0.66) | — | 2 | 2 | 0 | 98.3/181.5 | 0.0624 |
| fireworks:high | muse-spark-open | 14 | 1.000 | 45.700 [-85.7, 214.3] | 2 / 4 | 0/14 (CI 0.00–0.21) | 0/2 (CI 0.00–0.66) | — | 0 | 0 | 0 | 192.7/293.1 | 0.0548 |

Regret: agent branch objective minus planner branch objective in one shared audit comparison (16 members, seed 777, 180-min horizon; positive means the agent's choice is worse under the simulator's cost model). Mean-regret CIs are percentile bootstrap; rate CIs are Wilson 95%. 'Unsafe choice' = the recommended action still shows failures in the audit ensemble. Per-run detail is in `evaluation.json`.

### Re-check on verifier v4 with the information gate

Live model comparison: 2 arms × 7 cases × 2 repeats = 28 runs, total estimated cost $1.71. Cases: cooling_degradation@100min/s7, cooling_degradation@100min/s2011, bearing_deterioration@120min/s7, bearing_deterioration@120min/s2011, overload@60min/s7, overload@60min/s2011, healthy@100min/s7.
Generated 2026-10-29T19:36:57+00:00 · git `8c3d04a-dirty`.
Verifier: v4 + information gate.

| arm | model | runs | completed | mean regret $ (95% CI) | worse / better | unsafe choice | healthy false alarm | held for data | rejections | fallbacks | halluc. ids | p50/p95 latency (s) | cost $ / run |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| meta:high | muse-spark-1.3 | 14 | 1.000 | 117.900 [-50.0, 421.4] | 1 / 4 | 0/14 (CI 0.00–0.21) | 0/2 (CI 0.00–0.66) | 0 | 0 | 1 | 0 | 134.7/194.2 | 0.0642 |
| fireworks:high | muse-spark-open | 14 | 1.000 | 172.900 [-32.1, 477.1] | 2 / 4 | 0/14 (CI 0.00–0.21) | 0/2 (CI 0.00–0.66) | 0 | 0 | 0 | 44 | 157.1/189.3 | 0.0578 |

Regret: agent branch objective minus planner branch objective in one shared audit comparison (16 members, seed 777, 180-min horizon; positive means the agent's choice is worse under the simulator's cost model). Mean-regret CIs are percentile bootstrap; rate CIs are Wilson 95%. 'Unsafe choice' = the recommended action still shows failures in the audit ensemble. Per-run detail is in `evaluation.json`.

## 8. Limitations

- All data is synthetic, produced by the project's own digital twin; the twin's physics and fault models are simplified (lumped thermal node, parametric bearing damage growth).
- The predictive models are trained and tested on the same simulator family, so test results measure generalisation across randomized episodes, not transfer to real machines.
- Intervention outcomes depend on illustrative economic parameters (simulation/params.py).
- In the closed-loop evaluation, approvals are auto-granted by the harness; the live system requires explicit human approval.
- The closed-loop agent is the deterministic planner; live model runs (Meta Model API and Fireworks AI) are reported separately as single-decision snapshots, not closed-loop episodes. The planner, the verifier, and the regret audit share the same simulator.
- Sample sizes are small (a handful of episodes per scenario), so confidence intervals are wide.
- The information gate (foresight_active) was designed after inspecting failures on the first 5 test seeds. Two later changes (the agent trigger also fires on the hard alarm; the planner may also propose an immediate inspection for cooling and bearing faults) were made after inspecting the next 10 seeds. Only the last 5 test seeds were never inspected; results from before those changes are kept in evaluation_pre_trigger_fix.{json,md}.
- The live v4 snapshot cases never triggered the information gate (0/28 held): those decision points have supported trends. Fireworks cited 44 unknown evidence ids in hypotheses on 2 of 14 v4 runs; the verifier still accepted the final submissions (0 rejections).
