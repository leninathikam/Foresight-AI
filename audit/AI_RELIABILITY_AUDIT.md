# FORESIGHT AI — AI & ML SYSTEM RELIABILITY AUDIT

**Audit Phase:** Phase 3 (AI/ML System Audit)  
**Evaluator:** Staff AI/ML Engineer & Agent Architect  
**Codebase:** `E:\Hackathons\foresight-ai`  
**Commit:** `8c3d04a`  

---

## 1. Inventory of AI/ML Capabilities

Foresight AI integrates both classical predictive machine learning and agentic generative reasoning:

| Component | Architecture / Model | Target Output | Calibration / Bounds |
| :--- | :--- | :--- | :--- |
| **Failure Risk (15 min)** | XGBoost Classifier (300 trees, depth 4) | $P(\text{failure within 15 min})$ | Isotonic Regression on held-out validation |
| **Failure Risk (30 min)** | XGBoost Classifier (300 trees, depth 4) | $P(\text{failure within 30 min})$ | Isotonic Regression on held-out validation |
| **Failure Risk (60 min)** | XGBoost Classifier (300 trees, depth 4) | $P(\text{failure within 60 min})$ | Isotonic Regression on held-out validation |
| **Anomaly Detection** | Isolation Forest (200 estimators) | Anomaly score & binary flag | Threshold set at 95th quantile of healthy validation |
| **Change-Point Detection** | Upward CUSUM on 3 physical residuals | Sudden step/drift detection | Drift & threshold tuned to minimize detection delay |
| **Fault Diagnosis** | Multi-class XGBoost (`multi:softprob`) | Probabilities: none, cooling, bearing, overload | Supervised classification on 16 physics features |
| **Agent Reasoning** | Meta Muse Spark 1.3 / Muse Spark Open | Hypotheses, tool calls, verified proposals | Bounded state machine; strict JSON schemas; fallback |

---

## 2. Predictive ML Audit (Calibration & Accuracy)

### 2.1 Model Evaluation Metrics (Test Split: 80 episodes, 23,281 rows)
From the verified artifact `artifacts/reports/evaluation.md`:

| Horizon | Prevalence | Calibrated PR-AUC | Raw PR-AUC | Logistic Baseline | Alarm Rule Baseline | Calibrated Brier | Calibrated ECE |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **15 min** | 0.029 (675/23281) | **0.968** | 0.974 | 0.942 | 0.649 | **0.003** | **0.002** |
| **30 min** | 0.058 (1350/23281) | **0.949** | 0.960 | 0.949 | 0.649 | **0.009** | **0.006** |
| **60 min** | 0.116 (2700/23281) | **0.935** | 0.941 | 0.922 | 0.602 | **0.023** | **0.011** |

### Findings & Observations:
1. **Exceptional Calibration:** The Expected Calibration Error (ECE) of 0.002 to 0.011 and Brier scores $\le 0.023$ confirm that model output probabilities correspond closely to true empirical failure frequencies.
2. **False Alarm Suppression:** On 20 held-out healthy test episodes, the calibrated XGBoost model produced **0 false alarms** (0/20) across all three horizons.
3. **Detection Lead Time:** Median detection lead times are 14.5 minutes (15-min horizon), 29.7 minutes (30-min horizon), and 54.8 minutes (60-min horizon), providing operators with actionable advance warning.
4. **Diagnosis Accuracy:** Supervised fault classification achieves 97.5% overall accuracy and 99.6% accuracy on rows evaluated 30 minutes after fault onset.

---

## 3. Agent Architecture & Orchestration Audit

### 3.1 Bounded State Machine Transition Flow
The agent orchestrator enforces an explicit state transition matrix ([schemas.py#L25-L35](file:///E:/Hackathons/foresight-ai/packages/foresight/src/foresight/agents/schemas.py#L25-L35)):

$$\text{OBSERVE} \longrightarrow \text{ANALYZE} \longrightarrow \text{HYPOTHESIZE} \longrightarrow \text{INVESTIGATE} \longrightarrow \text{SIMULATE} \longrightarrow \text{VERIFY} \longrightarrow \text{RECOMMEND} \longrightarrow \text{DONE}$$

- Transitions are validated at runtime; illegal skips trigger `RuntimeError`.
- If the model attempts an action out of sequence, the tool stage router maps the call to the appropriate stage or rejects it.
- Tool call count is strictly bounded (`FORESIGHT_AGENT_MAX_TOOL_CALLS = 12`).
- Verifier revisions are capped at 2 (`FORESIGHT_AGENT_MAX_REVISIONS = 2`).

### 3.2 Tool Calling & Grounding
The agent has access to 9 typed tools ([prompts.py#L156-L270](file:///E:/Hackathons/foresight-ai/packages/foresight/src/foresight/agents/prompts.py#L156-L270)).
Crucially:
- Tools execute synchronously or in worker threads on a **frozen session snapshot** ([tools.py#L40-L50](file:///E:/Hackathons/foresight-ai/packages/foresight/src/foresight/agents/tools.py#L40-L50)). The model cannot manipulate the live digital twin.
- Sensor channels are validated against an enum.
- `inspect_visual_evidence` returns an explicit `"unavailable"` status with an honest disclaimer: *"No camera or thermal-imaging source is configured for this simulated asset."*

---

## 4. Head-to-Head Provider Comparison (Meta vs Fireworks)

From empirical benchmarks conducted across 126 runs on verifier v2, 28 runs on verifier v3, and 28 runs on verifier v4:

| Evaluation Wave | Model / Arm | Runs | Completion Rate | Mean Regret vs Planner ($) | 95% CI ($) | Unsafe Picks | Hallucinated Evidence IDs | Fallbacks to Optimizer |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **v2 (126 runs)** | Meta Muse Spark 1.3 (Low) | 21 | 100% | +$3.30 | [-57.1, 91.0] | 0 / 21 | 0 | 6 / 21 |
| | Meta Muse Spark 1.3 (Med) | 21 | 100% | -$3.80 | [-66.7, 83.8] | 0 / 21 | 0 | 4 / 21 |
| | Meta Muse Spark 1.3 (High) | 21 | 100% | **-$21.40** | [-50.0, 0.0] | 0 / 21 | 0 | 4 / 21 |
| | Fireworks Muse Spark Open (Low) | 21 | 90.5% | +$328.40 | [40.0, 664.2] | 0 / 19 | 0 | 0 / 21 |
| | Fireworks Muse Spark Open (Med) | 21 | 100% | +$130.50 | [-35.7, 364.8] | 0 / 21 | 0 | 0 / 21 |
| | Fireworks Muse Spark Open (High) | 21 | 95.2% | +$121.00 | [-70.0, 377.0] | 0 / 20 | 0 | 0 / 21 |
| **v4 (28 runs)** | Meta Muse Spark 1.3 (High) | 14 | 100% | +$117.90 | [-50.0, 421.4] | 0 / 14 | **0** | 1 / 14 |
| | Fireworks Muse Spark Open (High) | 14 | 100% | +$172.90 | [-32.1, 477.1] | 0 / 14 | **44** (in 2 runs) | 0 / 14 |

### Key Findings:
1. **Regret & Action Selection:** Meta Muse Spark 1.3 consistently picks actions closer to the cost-optimal choice than Fireworks Muse Spark Open. At high effort on v2, Meta beat the deterministic planner by \$21.40 on average, whereas Fireworks tended to pick more conservative, costlier actions (e.g. immediate shutdown).
2. **Hallucination Finding (Fireworks Open Weights):** In the v4 benchmark, Fireworks generated **44 unknown evidence IDs** in hypotheses across 2 of 14 runs ([evaluation.md#L346](file:///E:/Hackathons/foresight-ai/artifacts/reports/evaluation.md#L346)). The verifier successfully caught and filtered these before final submission.
3. **Fallback Robustness:** In 4–6 of 21 runs per arm on v2, Meta ended without submitting a verified proposal within budget. In all cases, the system cleanly engaged `_optimizer_fallback` ([orchestrator.py#L557-L617](file:///E:/Hackathons/foresight-ai/packages/foresight/src/foresight/agents/orchestrator.py#L557-L617)), verified the top candidate, and delivered an approved action.

---

## 5. Economic Performance: Foresight AI vs. Classical Baselines

One of the most impressive aspects of this project is its honest reporting of economic outcomes across closed-loop episodes (seeds 2000–2004, 6 hours per episode):

| Policy / Agent | Failures | Mean Cost ($) | Δ Cost vs None ($) | Healthy Touched | Downtime (h) |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **No Action** | 10 / 20 | \$16,835 | — | 0 / 5 | 0.00 h |
| **Rule: Derate on Alarm** | 0 / 20 | \$3,211 | -\$13,624 | 0 / 5 | 0.46 h |
| **Rule: Shutdown on Alarm** | 0 / 20 | \$2,899 | -\$13,936 | 0 / 5 | 1.70 h |
| **Rule: Inspect on Alarm** | **0 / 20** | **\$1,473** | **-\$15,363** | **0 / 5** | **1.08 h** |
| **ML Inspect on Risk** | 0 / 20 | \$2,754 | -\$14,081 | 0 / 5 | 2.44 h |
| **Foresight Estimated (No Gate)** | 0 / 20 | \$1,765 | -\$15,070 | 0 / 5 | 1.65 h |
| **Foresight Active (With Information Gate)** | 0 / 20 | \$1,647 | -\$15,188 | 0 / 5 | 1.54 h |
| **Foresight Oracle (Upper Bound)** | 0 / 20 | \$1,470 | -\$15,366 | 0 / 5 | 1.61 h |

### Critical Technical Takeaway:
The simple heuristic `rule_inspect_on_alarm` achieved \$1,473 mean cost, beating Foresight Active's \$1,647!  
**Why?** The rule triggers immediate physical maintenance the instant sensor limits are breached, incurring minimal downtime. Foresight AI explores multi-step actions (load reduction, auxiliary cooling), which incur slight operational losses before scheduling an inspection.  
**Value of Future Branching:** Future Branching significantly outperforms pure ML triggering (`ml_inspect_on_risk` at \$2,754), proving that counterfactual simulation adds massive value over simple ML prediction.
