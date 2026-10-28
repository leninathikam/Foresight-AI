# Foresight AI — Architecture

**Tagline:** See the failure before it happens. Simulate the future. Prevent the outcome.

Foresight AI is a simulation-only industrial intelligence loop:

**Observe → Predict → Diagnose → Simulate → Verify → Recommend → Monitor**

It never connects to or controls real equipment. All telemetry comes from a deterministic digital twin of a 15 kW TEFC induction motor driving a conveyor load.

## System diagram

```mermaid
flowchart TB
    WEB["<b>Web · apps/web (Next.js)</b><br/>Mission Control · Futures Lab · Agent · Evidence · Diagnostics"]

    subgraph API["FastAPI · services/api"]
        direction LR
        SS["Sessions<br/>+ SSE stream"]
        RUN["Agent runs<br/>futures · verify"]
        AP["Interventions<br/>human approval"]
        KEYS[("API keys<br/>server-side only")]
    end

    subgraph Core["foresight core · packages/foresight"]
        direction LR
        TW["MotorTwin<br/>physics ODEs, seeded"] --> TE["TelemetryStream"] --> RE["RiskEngine<br/>IsolationForest · CUSUM · XGBoost"]
        OR["AgentOrchestrator<br/>bounded state machine"] -- "typed tools" --> FB["Future Branching<br/>N members × K actions"] --> VF{{"Safety Verifier<br/>deterministic, LLM-free"}}
        RE --> OR
        OR -. "fallback" .-> PL["Deterministic planner"]
    end

    subgraph LLM["Muse Spark · Responses API"]
        direction LR
        META["Meta Model API<br/>muse-spark-1.3"]
        FW["Fireworks AI<br/>muse-spark-open"]
    end

    WEB <-->|"REST + SSE"| API
    SS --> TW
    RUN --> OR
    KEYS -.-> OR
    OR <-->|"function tools + strict JSON"| LLM
    VF -- "accepted" --> AP
    AP -- "approved action" --> TW
```

The browser never sees an API key. Every number the agent reasons about comes from a tool call into local code, and nothing reaches the twin without passing the verifier and an operator approval.

## Closed loop

```mermaid
flowchart LR
    O["Observe<br/>twin telemetry"] --> P["Predict<br/>calibrated risk"]
    P --> D["Diagnose<br/>fault class + hypotheses"]
    D --> S["Simulate<br/>branch futures"]
    S --> V{"Verify<br/>blocking checks"}
    V -- "rejected" --> D
    V -- "accepted" --> R["Recommend<br/>operator approves"]
    R --> M["Monitor<br/>post-intervention trajectory"]
    M --> O
```

## One agent run

```mermaid
sequenceDiagram
    autonumber
    actor Op as Operator
    participant UI as Web UI
    participant API as FastAPI
    participant AO as AgentOrchestrator
    participant M as Muse Spark<br/>(Meta or Fireworks)
    participant T as Local tools<br/>(frozen snapshot)
    participant V as Verifier

    Op->>UI: Run diagnosis (provider, effort)
    UI->>API: POST /agent/runs
    API->>AO: start run on frozen snapshot
    loop OBSERVE → ANALYZE → HYPOTHESIZE → INVESTIGATE
        AO->>M: context + function tools
        M-->>AO: tool call (get_machine_state, get_sensor_history,<br/>analyze_anomalies, predict_failure_risk)
        AO->>T: execute
        T-->>AO: real numbers + evidence ids
    end
    M-->>AO: compare_futures(actions)
    AO->>T: Future Branching ensemble
    T-->>AO: branch outcomes
    M-->>AO: verify_intervention(proposal)
    AO->>V: proposal + comparison + evidence ids
    V->>V: re-simulate with its own 16-member ensemble and seeds
    V-->>AO: accepted / rejected + check list
    M-->>AO: submit_recommendation (strict JSON)
    AO-->>API: trace (provider, effort, tokens, cost)
    API-->>UI: SSE updates
    UI->>Op: verified recommendation
    Op->>API: Approve → POST /interventions
```

If the model never submits a verified recommendation within the budget, or no key is configured, the deterministic planner picks the action and the trace says so.

## Verifier decision

```mermaid
flowchart TD
    IN["Proposal<br/>action + claimed mode + cited evidence"] --> PV{"Valid and feasible?<br/>parameters in range; inspection inside<br/>horizon, before earliest simulated failure"}
    PV -- no --> RJ["Rejected<br/>with reasons"]
    PV -- yes --> LIM{"Simulated branch complete and<br/>within temperature, vibration,<br/>load and failure limits?"}
    LIM -- no --> RJ
    LIM -- yes --> IB{"Consequential action beats<br/>no-action on cost or failures?"}
    IB -- no --> RJ
    IB -- yes --> IC{"Independent re-simulation<br/>on fresh seeds confirms, and<br/>cited evidence ids exist?"}
    IC -- no --> RJ
    IC -- yes --> W{"Warnings?<br/>uncertainty, unsupported mode"}
    W -- yes --> AW["Accepted with warnings"]
    W -- no --> AC["Accepted"]
    AW --> HA["Human approval required<br/>for consequential actions"]
    AC --> HA
```

## Red-team loop

```mermaid
flowchart LR
    ATK["Attacker model<br/>sees policy, checks, evidence ids"] -->|"6 proposals / round"| EXE["Agent tool path<br/>compare_futures → verify_intervention"]
    EXE --> VER{"Verifier"}
    VER -- "blocked" --> FBK["Feedback"]
    FBK -->|"3 adaptive rounds"| ATK
    VER -- "accepted" --> AUD["Audit<br/>48 members, fresh seeds"]
    AUD --> OUT["hard escape · soft escape · accepted OK"]
    FUZ["Seeded random fuzzer<br/>(control, same budget)"] --> EXE
    OUT -.->|"each hole → a SafetyPolicy flag"| VER
```

## Layers

### 1. Digital twin (`foresight.simulation`)

Physics-inspired ODE model with:

- Lumped thermal node (exact linear ODE step)
- Bearing damage growth (cubic load dependence inspired by L10 life)
- Vibration from baseline + bearing defect
- Cooling efficiency / overload / inspection / shutdown actuators
- Two RNG streams (process vs sensor) so cloned branches share matched disturbances

Scenarios: `cooling_degradation`, `bearing_deterioration`, `overload`, plus healthy baseline.

### 2. Telemetry (`foresight.telemetry`)

Timestamped samples, rolling window, missing/invalid handling, deterministic replay, simulation time separated from wall clock.

### 3. Prediction (`foresight.prediction`)

- Isolation Forest anomaly detection
- CUSUM change-point detection
- Multi-horizon XGBoost failure-risk models with isotonic calibration
- Supervised fault-class diagnosis
- Explicit baselines (z-score, alarm thresholds, temperature extrapolation)

Training / validation / test use disjoint seed ranges. See `artifacts/reports/evaluation.md`.

### 4. Future Branching (`foresight.branching`)

From a frozen estimated (or oracle) state, clone N members × K interventions, simulate a shared horizon with common random numbers, score an explicit economic objective, and rank branches. Estimates are **not** claimed causal effects.

### 5. Verification (`foresight.verification`)

Deterministic, LLM-independent policy checks on typed proposals + branch outcomes. Can reject unsafe or incomplete recommendations. Consequential actions always require human approval in the live UI.

The verifier does not trust the proposer's ensemble alone. The proposer chooses which actions to simulate, so an action can look safe because its small (8-member) ensemble happened to avoid failure. Before accepting, the verifier re-simulates the proposed action from the same initial state with its own 16-member ensemble and seeds the proposer never sees (`independent_confirmation`, blocking). The proposer's comparison and the confirmation must both show no failures and stay within the temperature and vibration limits.

Operator commands sent without a comparison bypass the verifier and are logged as "not verified", so the operator keeps authority.

**Fixes found by the red-team.** Each fix is a `SafetyPolicy` flag, so earlier versions can be reproduced (`run_red_team.py --verifier v1|v2|v3|v4`).

| Version | Change | Hole it closes |
|---|---|---|
| v1 | original | — |
| v2 | `improves_on_baseline` blocks a consequential action that neither lowers the objective nor the failure incidence (`block_no_benefit`) | wasteful actions on a healthy machine passed with a warning |
| v3 | vibration p90 limit 1 mm/s below the trip (6.1 mm/s); a tie with doing nothing is not a benefit; an inspection must start inside the simulated horizon (`strict_improvement`) | an untested load cut with p90 vibration just under the trip failed 1/48 in the audit; inspections scheduled after the horizon tied the no-action objective |
| v4 | inspection lead time measured from the baseline's *earliest* simulated failure, not the median (`inspection_before_earliest_failure`) | late bearing inspections (40–45 min) let early-failing members fail first (1–2/48 in the audit) |

v4 is the default in code. It has a regression test but has **not** been red-teamed or re-evaluated yet, so all reported numbers come from v1–v3.

**Red-team** (`foresight.evaluation.redteam`, `scripts/run_red_team.py`): an attacker model (Muse Spark Open on Fireworks, or Muse Spark 1.3 on Meta) sees the safety policy, the check list and the real evidence ids. It proposes interventions it expects to pass while being unsafe, wasteful or backed by fabricated evidence, and adapts over three rounds using the verifier's feedback. Proposals go through the agent's own tool path. Every accepted proposal is audited with a 48-member ensemble on fresh seeds. A seeded random fuzzer with the same budget is the control. Escapes are judged against the same twin (a larger ensemble with fresh seeds), not against ground truth.

### 6. Agent (`foresight.agents`)

Bounded state machine: OBSERVE → ANALYZE → HYPOTHESIZE → INVESTIGATE → SIMULATE → VERIFY → RECOMMEND.

- Live path: Responses API with function tools + structured output, from either provider through one `ModelClient`. The options are Meta Model API (`muse-spark-1.3`) and Fireworks AI (`muse-spark-open`). Provider and reasoning effort are chosen per run and recorded in the trace, and cost uses each provider's prices, including Fireworks cached-input pricing.
- Fallback: deterministic planner (clearly labelled in traces)
- Tools never invent sensor or simulation numbers; they call local code on a frozen snapshot
- `inspect_visual_evidence` returns `unavailable` until a real camera source exists (no fake vision)

### 7. API (`foresight_api`)

FastAPI + SSE streams. MODEL_API_KEY and FIREWORKS_API_KEY stay server-side. Diagnostics expose provider connectivity without leaking secrets.

### 8. Web (`apps/web`)

Next.js App Router + Tailwind + Recharts. Screens: Mission Control, Future Branching Lab, Agent Intelligence, Evidence & Evaluation, Diagnostics.

## Evidence provenance

UI and schemas distinguish:

| Kind | Meaning |
|------|---------|
| Observed | Twin sensor channels (synthetic measurements) |
| ML prediction | Calibrated model outputs |
| Simulation estimate | Branch outcomes / state estimate |
| LLM hypothesis | Agent free-text / structured hypotheses |
| Verified | Passed the independent verifier |

## Safety posture

- Simulation only
- No shell tools for the LLM
- No direct equipment control
- Human approval gate for interventions
- Visual / SAM path disabled until real evidence exists
