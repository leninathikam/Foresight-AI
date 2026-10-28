# Implementation checklist

Updated: 2026-10-28

## Milestone status

| Milestone | Status | Evidence |
|-----------|--------|----------|
| 1. Functional simulation | **Done** | `tests/unit/test_simulation.py`, `scripts/smoke_pipeline.py` |
| 2. Prediction | **Done** | Trained bundle + `artifacts/reports/evaluation.md` predictive tables |
| 3. Future Branching + verification | **Done** | `tests/unit/test_branching_and_verification.py`, `tests/unit/test_redteam.py` |
| 4. Meta-powered agent | **Done** | Two providers (Meta Model API `muse-spark-1.3`, Fireworks `muse-spark-open`). 126-run provider × effort comparison plus a 28-run re-check in `evaluation.md` §6 |
| 5. Product UI | **Done (local)** | Mission Control / Futures / Agent (provider + effort selector) / Evidence (comparison + red-team tables) / Diagnostics (per-provider checks) |
| 6. Evaluation + submission pack | **Mostly done** | Reports committed. Public repo, demo video and submission pending |

## Verified locally

- `pytest`: **76 passed** on verifier v3; `ruff` clean; `tsc --noEmit` and `eslint` clean
- Offline evaluation re-run on verifier v3: closed-loop results unchanged (Foresight 0/20 failures, no healthy episode touched)
- Live runs: 126 (verifier v2) + 28 (verifier v3). Red-team: 265 + 264 + 370 attempts against v1, v2 and v3
- Live API spend for these experiments: about $12.5 (comparison $5.65, re-check $1.64, red-team about $5.2), split across both providers

## Not yet verified

- **Verifier v4** (inspection lead time measured from the earliest simulated failure). It is the default in code and has a regression test, but the full test suite, the offline evaluation and a red-team run have not completed on it. Windows Application Control intermittently blocked the Python extension modules (`unicodedata`, scikit-learn) during those runs. To finish:
  1. `uv run pytest`
  2. `uv run python scripts/run_evaluation.py`, then merge back the saved live blocks (`artifacts/reports/live_eval_verifier_v2.json` and the `live_recheck` block)
  3. `uv run python scripts/run_red_team.py --verifier v4 --attackers fireworks:high,meta:high --max-output-tokens 20000`
- Visual check of the new Agent / Diagnostics / Evidence panels in the browser

## Remaining before submission

1. Commit and push a public repository
2. Record the 3-minute demo video
3. Accept the Official Rules and submit on Cerebral Valley by Nov 4, 9 PM ET

## Explicitly not claimed

- Real-plant safety or transfer learning
- Live SAM 3.1 vision (disabled until camera evidence exists)
- Live inference without a configured key
- That red-team escapes are judged against ground truth: they are judged against a larger ensemble of the same twin
- That zero escapes proves the verifier is safe: each red-team round found a subtler hole
