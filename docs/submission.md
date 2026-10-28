# Hackathon submission draft — Meta Global AI Developer Hackathon 2026

**Track:** Indie Developer  
**Theme:** Push the Frontier  
**Product:** Foresight AI  
**Deadline:** November 4, 2026, 9:00 PM Eastern  

> Confirm final Official Rules text on Cerebral Valley before submit. Scoring weights below follow the event waiver summary; verify against the published rules.

## One-liner

Foresight AI is a simulation-only motor digital twin that predicts failures, branches counterfactual interventions, independently verifies recommendations, and uses Meta Muse Spark as a bounded tool-calling agent.

## Short description (≈150–200 words)

Industrial monitoring usually raises alarms after thresholds are crossed. It rarely answers: *if we intervene now, which future is safer?* Foresight AI closes that loop on a reproducible digital twin of a VFD-driven TEFC induction motor.

The twin emits deterministic telemetry for cooling degradation, bearing deterioration, and overload. Calibrated ML models estimate multi-horizon failure risk and fault class. A Future Branching engine clones the estimated state, applies candidate interventions under matched noise, and scores an explicit economic objective. A deterministic safety verifier — independent of any LLM — can reject unsafe proposals, and it re-simulates each proposal with its own ensemble and seeds so an action cannot pass on a lucky sample. A bounded agent calls typed tools for observation, prediction, simulation and verification. It runs on Meta Muse Spark: Muse Spark 1.3 on the Meta Model API or the open-weights Muse Spark Open on Fireworks AI, selectable per run, with a labelled deterministic planner when no key is set. Consequential actions require human approval. The system is simulation-only and never controls real equipment.

Evaluation on held-out simulator seeds reports precision/recall/PR-AUC, detection lead time, calibration (Brier/ECE), closed-loop failure incidence against rule baselines, and agent reliability. A 126-run head-to-head compares the two Muse Spark endpoints across reasoning efforts. Both models also attacked the verifier as adaptive white-box red-teamers. Each round found a subtler hole (wasteful actions on a healthy machine, near-trip vibration, late inspections), and each was fixed and re-tested. Visual/SAM inspection is explicitly unavailable until a real camera source exists.

## How Meta models are used

| Model | Role |
|-------|------|
| `muse-spark-1.3` (Meta Model API) | Diagnostic reasoning, tool selection, structured recommendations (Responses API). Red-team attacker |
| `muse-spark-open` (Fireworks AI) | The same agent on open weights, selectable per run. Head-to-head comparison and red-team attacker |
| Deterministic planner | Fallback when no API key — clearly labelled in traces |
| SAM 3.1 | **Not claimed in demo** — `inspect_visual_evidence` returns unavailable |

## Bonus-award angles (if offered)

- **Best Agentic Use-Case:** bounded tool loop with verifier rejections and human approval
- **Best Build on Meta Open Weight Models:** Muse Spark Open on Fireworks AI runs the full agent and the red-team, and is compared head-to-head with Muse Spark 1.3

## Links to prepare

- Public GitHub repo
- Live demo URL (or local-run README)
- 3-minute demo video following `docs/demo-script.md`
- Evaluation report: `artifacts/reports/evaluation.md`; red-team reports: `artifacts/reports/redteam_v1.md` – `redteam_v3.md`

## Checklist before submit

- [ ] Official rules accepted on Cerebral Valley
- [ ] Repo public; secrets absent (`.env` gitignored)
- [ ] README runs clean on a fresh machine
- [ ] Live Meta smoke test on Diagnostics (if claiming Muse Spark)
- [ ] Demo video recorded from working UI
- [ ] Evaluation numbers match last `scripts/run_evaluation.py` run
- [ ] Limitations section honest (synthetic data, no real-plant transfer)
