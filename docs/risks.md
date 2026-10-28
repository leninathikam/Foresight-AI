# Risks and limitations

## Technical

| Risk | Mitigation |
|------|------------|
| Synthetic-only data → optimistic metrics | Report clearly; no real-machine claims |
| LLM invents numbers | Tools compute all quantities; structured schemas; verifier ignores free text |
| Verifier shares simulator with planner | Documented; oracle vs estimated branching comparison in eval |
| Meta API outage / missing key | Deterministic planner fallback; Diagnostics honesty |
| SAM/vision incomplete | Tool returns `unavailable`; feature not demoed as live |
| Docker/Next standalone quirks | Document local `uv` + `npm` path as primary |

## Product / judging

| Risk | Mitigation |
|------|------------|
| Looks like a dashboard | Demo script centers branching + verifier rejection |
| Impact score soft for sim-only | Pitch as frontier method for intervention selection; kit/sim is the measurable sandbox |
| Scope creep | Freeze features; polish demo path |

## Safety

- Simulation only; no equipment control
- Human approval for consequential interventions
- No LLM shell access
- Secrets never in `NEXT_PUBLIC_*` or the browser
