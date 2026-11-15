# Idea and Prototype One-Pager: Foresight-AI

**Project:** Foresight-AI — Industrial Operations Copilot & Deterministic Future Arena  
**Hackathon Track:** Berkeley x DeepMind Hackathon Online Track  
**Repository:** [https://github.com/leninathikam/Foresight-AI](https://github.com/leninathikam/Foresight-AI)  
**Branch:** `feat/berkeley-hackathon-gemini-arena`  

---

## 1. The Core Problem: The Industrial Hallucination Trap

In heavy manufacturing, oil & gas, mining, and power utilities, unplanned asset downtime costs an estimated **$50 billion annually**, with critical equipment outages costing up to **$22,000 per minute**.

While generative AI agents and LLMs have demonstrated remarkable reasoning across software engineering and document analysis, applying standard LLMs to industrial operations creates an immediate safety catastrophe:
1. **Unconstrained Parameter Hallucination**: LLMs fabricate sensor baselines, misread thermal time constants, and invent operating tolerances that violate basic physics.
2. **Blind Action Recommendation**: Without counterfactual simulation, agents cannot forecast the second-order physical consequences of an intervention. For example, derating a constant-torque induction motor reduces fan airflow faster than it reduces stator heat dissipation ($I^2 R$), triggering accelerated thermal burnout.
3. **Absence of Safety Boundaries**: Standard AI agents attempt direct actuation without an independent, fail-closed physics verifier or cryptographic audit trail.

---

## 2. The Solution: Foresight-AI

Foresight-AI bridges the gap between state-of-the-art generative intelligence and industrial physical safety through a closed-loop simulation architecture:

```
Telemetry Stream ──► Calibrated ML Risk ──► Gemini Copilot (Typed Tools) ──► Future Arena (CRN Branching)
                                                                                     │
Actuators Locked ◄── Human Approval Gate ◄── Decision Receipt ◄── Verifier v5 (Fail-Closed Gate)
```

### Key Innovations

#### 1. Gemini Operations Copilot (`google-genai` SDK v3.3.0)
* **SDK Integration**: Utilizes the official Google Gen AI SDK v3.3.0 targeting `gemini-3.8-flash`.
* **Typed Tool Calling**: Strict schema definition across 6 deterministic tools:
  * `get_machine_state`: Frozen telemetry snapshot (RPM, stator temperature, RMS vibration, load torque, efficiency).
  * `get_sensor_history`: Rolling time-series sensor windows.
  * `analyze_anomalies`: Isolation Forest and CUSUM change-point scores with statistical evidence IDs.
  * `predict_failure_risk`: Calibrated multi-horizon failure probabilities (15m, 30m, 60m).
  * `compare_futures`: Multi-scenario counterfactual simulations.
  * `verify_intervention`: Independent physics verification.
* **Stateful Turn Management**: Preserves exact multi-turn dialogue context with full schema validation and server-side credential isolation.
* **Transparent Fallback**: When Gemini API keys are omitted or rate-limited, the system executes deterministic planning, clearly labeled in UI and logs as deterministic fallback.

#### 2. Future Arena (3-Way Counterfactual Simulation)
* **Deterministic Digital Twin**: Simulates a 15 kW Totally Enclosed Fan-Cooled (TEFC) induction motor using coupled differential equations (stator copper loss, rotor slip, heat transfer, cubic-load bearing fatigue).
* **Common Random Numbers (CRN)**: Evaluates three distinct operational interventions under identical stochastic process noise:
  1. **Continue Operating (No Action)**: Baseline run showing exact time-to-failure (e.g., 308 minutes under cooling degradation).
  2. **Reduce Load (-30% derate)**: Tests whether load shedding stabilizes temperature or triggers cooling-collapse.
  3. **Planned Maintenance (Scheduled shutdown at t=60m)**: Replaces bearings or restores airflow at minimal economic cost.
* **Unified Economic Objective**: Quantifies downtime penalties ($500/hr), repair costs ($2,500 replacement vs $12,000 catastrophic replacement), and production loss.

#### 3. Safety Challenge & Verifier v5 (Fail-Closed Physical Gate)
* **13 Deterministic Physics Checks**: Validates temperature limits (Class F 155 °C), ISO 10816-3 vibration limits (7.1 mm/s trip, 6.1 mm/s safety margin), parameter feasibility, and evidence citations.
* **Independent Confirmation Protocol**: Proposed actions that pass initial screening are re-simulated across 32 fresh Monte Carlo seeds (+900,000 seed offset) to prevent small-sample optimizer luck.
* **Direct Actuation Barrier**: Physical hardware actuators remain locked in their last safe state until an accepted intervention is explicitly approved by a human operator.
* **Judge-Facing Challenge Suite**: Real-time adversarial benchmark that submits intentionally unsafe proposals (e.g. derating a failing bearing, hallucinating sensor IDs, deferring maintenance past failure) and proves Verifier v5 immediately rejects them with specific violated constraints.

#### 4. Multimodal Diagnostics & Tamper-Evident Decision Receipts
* **Multimodal Evidence**: Ingests thermographic infrared imagery and vibration spectrograms with strict MIME/magic byte validation, isolating model interpretation from raw extracted telemetry.
* **Decision Receipts**: Every operational recommendation generates a canonical SHA-256 JSON audit receipt logging input snapshot digests, model versions, counterfactual projections, verification check results, and operator approvals.

---

## 3. The 15-Second Judge Demo Flow

The Mission Control UI is engineered for instant clarity, guiding judges through the operational safety loop in under 15 seconds without requiring technical narration:

1. **Second 0–4 (Observe & Predict)**: Judge opens `/` (Mission Control). Live SSE telemetry pulses with motor parameters. Calibrated ML risk gauges alert to cooling degradation with a 60-minute failure risk of 88.4%.
2. **Second 5–9 (Future Arena)**: Judge navigates to `/arena`. With one click, the 3-way simulation executes. The comparative chart instantly reveals that *Continue Operating* leads to stator burnout at 308m ($14,500 cost), *Reduce Load* stalls cooling, while *Planned Maintenance* at 60m caps total cost at $3,100 with 0% failure probability.
3. **Second 10–13 (Safety Challenge)**: Judge navigates to `/safety-challenge` and fires an adversarial attack (`bearing_derate_trap`). Verifier v5 rejects the action in 12ms with red alert badges citing `limits_respected: FALSE (vibration 8.4 mm/s exceeds 6.1 mm/s safe margin)`. Actuation is blocked.
4. **Second 14–15 (Decision Receipt)**: Judge opens `/receipts`. A cryptographic SHA-256 seal guarantees that the verified maintenance decision is tamper-evident and audit-ready for regulatory compliance.

---

## 4. Engineering Verification Status

* **130 Tests Passing**: Complete regression suite covering unit tests, digital twin physics, CUSUM/XGBoost calibrated prediction, Gemini tool execution, adversarial safety rejection, and cryptographic hash verification.
* **Next.js 16 Production Build**: Clean production build with zero TypeScript or ESLint errors across all 8 frontend routes.
* **Zero Disguised Fallbacks**: Complete transparency in API responses, distinguishing live Gemini 3.8 Flash reasoning from deterministic backup planners.
