# Three-minute demo script

**Goal:** Show a working Observe → Predict → Diagnose → Simulate → Verify → Recommend loop on a live digital twin. All UI actions must succeed live.

**Prep:** API on `:8000`, web on `:3000`. Prefer a live `MODEL_API_KEY` so the Agent page uses Muse Spark; if unset, say clearly that the deterministic planner is running and show Diagnostics.

---

### 0:00–0:20 — Problem

Open **Mission Control**.

> “Conventional alarms tell you a motor is already hot. Foresight asks a harder question: what happens if we keep running, and which intervention is safest *before* the failure?”

Point at live telemetry (temperature, vibration, load, current) on a healthy cooling-degradation episode (seed 7).

### 0:20–0:50 — Failure injection

Click **Inject fault**. Speed sim to 60× if needed. Watch temperature climb and risk bars move.

> “We inject cooling degradation into the twin. Isolation Forest / change-points and calibrated XGBoost horizons update from the same telemetry window.”

### 0:50–1:20 — AI diagnosis

Open **Agent**. Run diagnosis.

> “A bounded Meta Muse Spark agent — or our labelled deterministic planner if no API key — calls tools for state, anomalies, and risk. It never invents sensor numbers.”

Show stages and tool timeline.

### 1:20–2:00 — Future Branching

Open **Futures Lab**. Compare Continue / Reduce load / Increase cooling / Inspection / Shutdown.

> “Same initial state, matched noise, same horizon. Side-by-side failure incidence, peak temperature, cost. Estimates — not proven causal effects.”

### 2:00–2:30 — Verification

Show verifier accepting inspection (or rejecting a delayed inspection on overload — seed from smoke: overload @ 60 min rejects “Inspection in 10 min”).

> “An independent policy engine can reject the agent. Unsafe or incomplete proposals never auto-apply.”

### 2:30–3:00 — Outcome

Approve the recommended action. Return to Mission Control; show trajectory diverge from the no-action mental baseline.

> “Human-approved intervention only. Simulation only — no real equipment. Full metrics and limitations are on Evidence.”

---

## Backup (no webcam / no API key)

1. Run `uv run python scripts/smoke_pipeline.py` — prints branching + agent traces for all three faults.
2. Open Evidence page with `artifacts/reports/evaluation.md` metrics.
3. On Diagnostics, show `llm_configured: false` honestly.
