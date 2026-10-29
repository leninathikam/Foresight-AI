"""Run the full evaluation and write artifacts/reports/evaluation.{json,md}.

Usage:
  uv run python scripts/run_evaluation.py [--seeds-per-scenario 5] [--live-agent] [--quick]

--live-agent calls real model endpoints (costs tokens) and only runs if the arm's key is set:
MODEL_API_KEY for meta, FIREWORKS_API_KEY for fireworks. Example head-to-head:
  uv run python scripts/run_evaluation.py --live-agent-only --repeats 3 \
      --arms meta:medium,fireworks:medium,meta:high,fireworks:high
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from datetime import UTC, datetime

from foresight.artifacts import REPO_ROOT, REPORTS_DIR, load_or_build_dataset, load_or_train_bundle
from foresight.config import get_settings
from foresight.evaluation.agent_eval import (
    Arm,
    carry_over_live_blocks,
    deterministic_agent_metrics,
    live_agent_metrics,
    parse_arms,
)
from foresight.evaluation.counterfactual import evaluate_counterfactual_calibration
from foresight.evaluation.interventions import evaluate_interventions
from foresight.evaluation.predictive import (
    evaluate_detection,
    evaluate_diagnosis,
    evaluate_risk,
    measure_latency,
)
from foresight.evaluation.report import render_markdown
from foresight.prediction.dataset import SPLIT_SEEDS
from foresight.verification import DEFAULT_POLICY

LIMITATIONS = [
    "All data is synthetic, produced by the project's own digital twin; the twin's physics and "
    "fault models are simplified (lumped thermal node, parametric bearing damage growth).",
    "The predictive models are trained and tested on the same simulator family, so test results "
    "measure generalisation across randomized episodes, not transfer to real machines.",
    "Intervention outcomes depend on illustrative economic parameters (simulation/params.py).",
    "In the closed-loop evaluation, approvals are auto-granted by the harness; the live system "
    "requires explicit human approval.",
    "The closed-loop agent is the deterministic planner; live model runs (Meta Model API and "
    "Fireworks AI) are reported separately as single-decision snapshots, not closed-loop "
    "episodes. The planner, the verifier, and the regret audit share the same simulator.",
    "Sample sizes are small (a handful of episodes per scenario), so confidence intervals are wide.",
    "The information gate (foresight_active) was designed after inspecting failures on the first "
    "5 test seeds. Two later changes (the agent trigger also fires on the hard alarm; the planner "
    "may also propose an immediate inspection for cooling and bearing faults) were made after "
    "inspecting the next 10 seeds. Only the last 5 test seeds were never inspected; results from "
    "before those changes are kept in evaluation_pre_trigger_fix.{json,md}.",
    "The live v4 snapshot cases never triggered the information gate (0/28 held): those "
    "decision points have supported trends. Fireworks cited 44 unknown evidence ids in "
    "hypotheses on 2 of 14 v4 runs; the verifier still accepted the final submissions "
    "(0 rejections).",
]

CONFIRMATION_NOTE = (
    "Same policies on the next 10 test seeds. They were clean for the information gate, but the "
    "alarm trigger and immediate-inspection candidates were added after inspecting them (an "
    "episode where the hard alarm fired 8 min before the end and Foresight never woke up)."
)
HOLDOUT_NOTE = (
    "Same policies on the last test seeds, never inspected during development: the clean check "
    "of every change, including the alarm trigger and immediate-inspection candidates."
)


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, timeout=10, check=True
    ).stdout.strip()


def _git_commit() -> str | None:
    """Short HEAD hash, suffixed with '-dirty' if the evaluated code differs from HEAD."""
    try:
        commit = _git("rev-parse", "--short", "HEAD")
        dirty = _git("status", "--porcelain", "--", "packages", "scripts")
    except (OSError, subprocess.SubprocessError):
        return None
    return f"{commit}-dirty" if dirty else commit


def _progress(done: int, total: int, r: dict) -> None:
    audit = r.get("audit") or {}
    print(
        f"[{done:>3}/{total}] {r['arm']:<18} {r['case']:<34} {r['status']:<9} "
        f"{r['action']!s:<26} regret={audit.get('regret_vs_planner')} "
        f"rej={r['rejections']} {r['latency_ms'] / 1000:.0f}s ${r['estimated_cost_usd']:.3f}",
        flush=True,
    )


def update_live_agent_only(
    repeats: int,
    arms: list[Arm] | None,
    concurrency: int,
    key: str = "live",
    verifier_label: str | None = None,
) -> None:
    path = REPORTS_DIR / "evaluation.json"
    if not path.exists():
        raise SystemExit("No evaluation.json yet; run the full evaluation first.")
    ev = json.loads(path.read_text(encoding="utf-8"))
    t0 = time.perf_counter()
    ev["agent"][key] = live_agent_metrics(
        load_or_train_bundle(),
        get_settings(),
        run=True,
        arms=arms,
        repeats=repeats,
        concurrency_per_provider=concurrency,
        on_progress=_progress,
    )
    if ev["agent"][key].get("status") != "run":
        raise SystemExit(f"Live evaluation not run: {ev['agent'][key].get('reason')}")
    ev["agent"][key]["generated_at"] = datetime.now(UTC).isoformat(timespec="seconds")
    ev["agent"][key]["git_commit"] = _git_commit()
    ev["agent"][key]["verifier_policy"] = DEFAULT_POLICY.model_dump(mode="json")
    if verifier_label:
        ev["agent"][key]["verifier_label"] = verifier_label
    path.write_text(json.dumps(ev, indent=2), encoding="utf-8")
    (REPORTS_DIR / "evaluation.md").write_text(render_markdown(ev), encoding="utf-8")
    print(f"live agent evaluation updated in {time.perf_counter() - t0:.0f}s")


def update_counterfactual_only(seeds_per_scenario: int) -> None:
    path = REPORTS_DIR / "evaluation.json"
    if not path.exists():
        raise SystemExit("No evaluation.json yet; run the full evaluation first.")
    ev = json.loads(path.read_text(encoding="utf-8"))
    t0 = time.perf_counter()
    ev["counterfactual"] = evaluate_counterfactual_calibration(seeds_per_scenario)
    ev["counterfactual"]["generated_at"] = datetime.now(UTC).isoformat(timespec="seconds")
    ev["counterfactual"]["git_commit"] = _git_commit()
    path.write_text(json.dumps(ev, indent=2), encoding="utf-8")
    (REPORTS_DIR / "evaluation.md").write_text(render_markdown(ev), encoding="utf-8")
    print(f"counterfactual calibration updated in {time.perf_counter() - t0:.0f}s")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seeds-per-scenario", type=int, default=5)
    parser.add_argument("--live-agent", action="store_true")
    parser.add_argument("--quick", action="store_true", help="2 seeds per scenario")
    parser.add_argument(
        "--live-agent-only",
        action="store_true",
        help="Re-run only the live model agent evaluation and update the existing report",
    )
    parser.add_argument("--repeats", type=int, default=2, help="Live agent runs per case")
    parser.add_argument(
        "--arms",
        default=None,
        help="Comma-separated provider:effort arms, e.g. meta:medium,fireworks:medium "
        "(default: the configured provider at the configured effort)",
    )
    parser.add_argument(
        "--concurrency", type=int, default=3, help="Concurrent live runs per provider"
    )
    parser.add_argument(
        "--confirmation-seeds",
        type=int,
        default=10,
        help="Closed-loop re-run on the next N unused test seeds (0 = skip)",
    )
    parser.add_argument(
        "--holdout-seeds",
        type=int,
        default=5,
        help="Closed-loop run on the last N test seeds, after the confirmation seeds (0 = skip)",
    )
    parser.add_argument("--counterfactual-seeds", type=int, default=10)
    parser.add_argument(
        "--skip-counterfactual",
        action="store_true",
        help="Keep the counterfactual block from the previous report instead of recomputing it",
    )
    parser.add_argument(
        "--counterfactual-only",
        action="store_true",
        help="Re-run only the counterfactual calibration and update the existing report",
    )
    parser.add_argument(
        "--live-key",
        default="live",
        help="Key under agent.* to write live results to (e.g. live_recheck)",
    )
    parser.add_argument("--verifier-label", default=None, help="Stored with live results")
    args = parser.parse_args()
    arms = parse_arms(args.arms) if args.arms else None
    if args.live_agent_only:
        update_live_agent_only(
            args.repeats, arms, args.concurrency, args.live_key, args.verifier_label
        )
        return
    if args.counterfactual_only:
        update_counterfactual_only(args.counterfactual_seeds)
        return
    seeds = 2 if args.quick else args.seeds_per_scenario
    previous_path = REPORTS_DIR / "evaluation.json"
    previous = (
        json.loads(previous_path.read_text(encoding="utf-8")) if previous_path.exists() else {}
    )

    t0 = time.perf_counter()
    bundle = load_or_train_bundle()
    validation = load_or_build_dataset("validation")
    test = load_or_build_dataset("test")
    print(f"data ready ({time.perf_counter() - t0:.0f}s): test rows {test.n_rows}")

    data = {}
    for split in ("train", "validation", "test"):
        ds_rows = bundle.metadata.get(f"{split}_rows") if split != "test" else test.n_rows
        ds_eps = bundle.metadata.get(f"{split}_episodes") if split != "test" else len(test.episodes)
        r = SPLIT_SEEDS[split]
        data[split] = {"episodes": ds_eps, "rows": ds_rows, "seeds": [r.start, r.stop - 1]}

    t1 = time.perf_counter()
    predictive = {
        "risk": evaluate_risk(bundle, validation, test),
        "detection": evaluate_detection(bundle, test),
        "diagnosis": evaluate_diagnosis(bundle, test),
        "latency": measure_latency(bundle, test),
    }
    print(f"predictive done ({time.perf_counter() - t1:.0f}s)")

    t2 = time.perf_counter()
    interventions = evaluate_interventions(bundle, seeds_per_scenario=seeds)
    print(f"interventions done ({time.perf_counter() - t2:.0f}s)")

    confirmation = None
    if args.confirmation_seeds and not args.quick:
        t3 = time.perf_counter()
        test_seeds = list(SPLIT_SEEDS["test"])
        confirmation = evaluate_interventions(
            bundle, seeds=test_seeds[seeds : seeds + args.confirmation_seeds]
        )
        confirmation["note"] = CONFIRMATION_NOTE
        print(f"confirmation done ({time.perf_counter() - t3:.0f}s)")

    holdout = None
    if args.holdout_seeds and not args.quick:
        t5 = time.perf_counter()
        start = seeds + args.confirmation_seeds
        holdout = evaluate_interventions(
            bundle, seeds=list(SPLIT_SEEDS["test"])[start : start + args.holdout_seeds]
        )
        holdout["note"] = HOLDOUT_NOTE
        print(f"holdout done ({time.perf_counter() - t5:.0f}s)")

    counterfactual = previous.get("counterfactual")
    if not args.skip_counterfactual:
        t4 = time.perf_counter()
        counterfactual = evaluate_counterfactual_calibration(
            seeds_per_scenario=2 if args.quick else args.counterfactual_seeds
        )
        print(f"counterfactual calibration done ({time.perf_counter() - t4:.0f}s)")

    agent = {
        "deterministic": deterministic_agent_metrics(interventions),
        "live": live_agent_metrics(
            bundle,
            get_settings(),
            run=args.live_agent,
            arms=arms,
            repeats=args.repeats,
            concurrency_per_provider=args.concurrency,
            on_progress=_progress,
        ),
    }
    agent = carry_over_live_blocks(agent, previous)

    ev = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "git_commit": _git_commit(),
        "model_version": bundle.version,
        "verifier_policy": DEFAULT_POLICY.model_dump(mode="json"),
        "data": data,
        "predictive": predictive,
        "interventions": interventions,
        "interventions_confirmation": confirmation,
        "interventions_holdout": holdout,
        "counterfactual": counterfactual,
        "agent": agent,
        "limitations": LIMITATIONS,
        "runtime_s": round(time.perf_counter() - t0, 1),
    }
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    (REPORTS_DIR / "evaluation.json").write_text(json.dumps(ev, indent=2), encoding="utf-8")
    (REPORTS_DIR / "evaluation.md").write_text(render_markdown(ev), encoding="utf-8")
    print(f"wrote {REPORTS_DIR / 'evaluation.json'} and evaluation.md in {ev['runtime_s']}s")


if __name__ == "__main__":
    main()
