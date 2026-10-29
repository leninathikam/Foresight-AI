# Implementation checklist

Updated: 2026-10-29

## Milestone status

| Milestone | Status | Evidence |
|-----------|--------|----------|
| 1. Functional simulation | **Done** | `tests/unit/test_simulation.py`, `scripts/smoke_pipeline.py` |
| 2. Prediction | **Done** | Trained bundle + `artifacts/reports/evaluation.md` predictive tables |
| 3. Future Branching + verification | **Done** | `tests/unit/test_branching_and_verification.py`, `tests/unit/test_redteam.py`, `tests/unit/test_information.py` |
| 4. Meta-powered agent | **Done** | Two providers (Meta Model API `muse-spark-1.3`, Fireworks `muse-spark-open`). 126-run comparison (v2) + 28-run re-check (v3) + 28-run re-check on v4 with the information gate in `evaluation.md` §7. |
| 5. Product UI | **Done (local)** | Mission Control / Futures / Agent (information-gate panel) / Evidence (confirmation, hold-out, calibration, red-team v4) / Diagnostics (both providers live-checked) |
| 6. Evaluation + submission pack | **Mostly done** | Offline report regenerated on v4. Public repo, demo video and Cerebral Valley submission pending |

## Verified locally (2026-10-29)

- `pytest`: **90 passed**; `ruff` check and format clean; `tsc --noEmit` and `eslint` clean
- Offline closed loop on verifier v4, three seed blocks, 0 failures on every intervening policy:
  - seeds 2000–2004: `foresight_active` mean cost $1,647 vs `foresight_estimated` $1,765 vs `rule_inspect_on_alarm` $1,473 vs no-action $16,835
  - confirmation 2005–2014 (gate-clean; trigger/inspection-delay changes inspected these): active $2,296 vs estimated $2,334 vs inspect $1,595
  - hold-out 2015–2019 (never inspected): active $2,645 vs estimated $2,722 vs inspect $1,498
- The inspect-on-alarm rule is still the cheapest policy. Future Branching beats the ML-only inspect trigger (`ml_inspect_on_risk`). The information gate modestly lowers cost vs estimated without adding a failure.
- Counterfactual calibration (116 decision points): peak-temperature 10–90 % coverage is 25 % overall, 41 % on active faults (nominal 80 %). 7 of 134 predicted-safe active-fault branches fail in the true process. 19 of 26 overall false-safe branches are latent faults the telemetry could not yet show.
- Verifier red-team v4: 366 attempts. Late-inspection escapes from v3 are gone. One distinct hard escape remains (35 % load cut on a bearing case, 1/48 audit failures, submitted 3 times). Fireworks 0 hard / 1 round lost; Meta 3 hard (that one proposal); random fuzz 0 hard.
- Browser: Diagnostics live-checked both providers (`ok: true`). Agent run on cooling seed 7 with Muse Spark 1.3 medium: inspection in 30 min accepted, information gate *act now* (cooling fouling t = 21.3).
- Live agent re-check on v4 + information gate (`agent.live_v4`, 28 runs, $1.71, generated 2026-10-29T19:36:57Z): 28/28 completed, 0 unsafe picks, 0 healthy false alarms, 0 rejections. Mean regret +$118 Meta / +$173 Fireworks (both CIs include 0). Three costlier-but-safe picks: two controlled shutdowns and one 40 % derate. One Meta optimizer fallback. Gate held 0/28 of these snapshots (supported trends). Fireworks invented 44 unknown evidence ids in hypotheses on 2/14 runs; final submissions still verified. One Fireworks HTTP 503 retried and recovered.
- Live API spend so far: about $16 (comparison $5.65, v3 re-check $1.64, v4 re-check $1.71, red-team v1–v3 ~$5.2, red-team v4 $1.59).

## Remaining before submission

1. Commit and push a public repository
2. Record the 3-minute demo video (`docs/demo-script.md`)
3. Confirm Official Rules on Cerebral Valley (the participant-facing copy was behind login) and submit by Nov 4, 9 PM ET
4. Optional: close the v4 tail-risk escape (larger confirmation ensemble or a stricter vibration margin for derating on bearing faults)
5. Optional: when remaining episode time is shorter than the inspection delay, prefer an immediate inspection — this is why cooling seed 2017 still costs $19,500
6. Optional: the information gate was not exercised by the live snapshot cases (all `act_now`); a dedicated live case with unsupported post-restart trends is still missing

## Explicitly not claimed

- Real-plant safety or transfer learning
- Live SAM 3.1 vision (disabled until camera evidence exists)
- Live inference without a configured key
- That red-team escapes are judged against ground truth: they are judged against a larger ensemble of the same twin
- That zero escapes proves the verifier is safe: each red-team round found a subtler hole
- That Future Branching beats a strong maintenance-aware rule: inspect-on-alarm is cheaper on every seed block
- That the estimated-state ensemble is well calibrated: p10–p90 temperature coverage is far below the nominal 80 %
- Readiness to submit: public repo, demo video and Cerebral Valley rules acceptance are still open
