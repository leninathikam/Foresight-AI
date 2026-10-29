"""Render the evaluation JSON as a Markdown report (no numbers are written by hand)."""

from __future__ import annotations


def _fmt(v, nd: int = 3) -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:.{nd}f}"
    return str(v)


def _table(header: list[str], rows: list[list]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(_fmt(c) for c in r) + " |" for r in rows]
    return "\n".join(lines)


def _ci(v) -> str:
    return "—" if not v else f"[{v[0]}, {v[1]}]"


def _rate(r: dict | None) -> str:
    if not r:
        return "—"
    return f"{r['k']}/{r['n']} (CI {r['ci95'][0]:.2f}–{r['ci95'][1]:.2f})"


def _live_arms_section(live: dict) -> list[str]:
    out = [
        f"Live model comparison: {len(live['arms'])} arms × {len(live['cases'])} cases × "
        f"{live['repeats']} repeats = {live['runs']} runs, total estimated cost "
        f"${live['estimated_cost_usd']:.2f}. Cases: {', '.join(live['cases'])}.",
    ]
    if live.get("generated_at"):
        out.append(f"Generated {live['generated_at']} · git `{live.get('git_commit')}`.")
    if live.get("verifier_label"):
        out.append(f"Verifier: {live['verifier_label']}.")
    out += [
        "",
        _table(
            [
                "arm",
                "model",
                "runs",
                "completed",
                "mean regret $ (95% CI)",
                "worse / better",
                "unsafe choice",
                "healthy false alarm",
                "held for data",
                "rejections",
                "fallbacks",
                "halluc. ids",
                "p50/p95 latency (s)",
                "cost $ / run",
            ],
            [
                [
                    a["arm"],
                    a["model"].rsplit("/", 1)[-1],
                    a["runs"],
                    a["completion_rate"],
                    f"{_fmt(a.get('mean_regret_vs_planner_usd'))} {_ci(a.get('mean_regret_ci95'))}",
                    f"{a.get('runs_worse_than_planner', '—')} / "
                    f"{a.get('runs_better_than_planner', '—')}",
                    _rate(a.get("unsafe_choice")),
                    _rate(a.get("healthy_false_intervention")),
                    "—"
                    if a.get("gather_information_rate") is None
                    else round(a["gather_information_rate"] * a["runs"]),
                    a["verifier_rejections"],
                    a["fallbacks"],
                    a["hallucinated_evidence_ids"],
                    f"{_fmt((a['latency_ms']['p50'] or 0) / 1000, 1)}/"
                    f"{_fmt((a['latency_ms']['p95'] or 0) / 1000, 1)}",
                    f"{a['estimated_cost_usd'] / a['runs']:.4f}",
                ]
                for a in live["arms"]
            ],
        ),
        "",
        f"Regret: agent branch objective minus planner branch objective in one shared audit "
        f"comparison ({live['audit']['members']} members, seed {live['audit']['seed']}, "
        f"{live['audit']['horizon_min']:.0f}-min horizon; positive means the agent's choice is "
        "worse under the simulator's cost model). Mean-regret CIs are percentile bootstrap; rate "
        "CIs are Wilson 95%. 'Unsafe choice' = the recommended action still shows failures in the "
        "audit ensemble. Per-run detail is in `evaluation.json`.",
    ]
    return out


def render_markdown(ev: dict) -> str:
    out = [
        "# Foresight AI — Evaluation Report",
        "",
        f"Generated: {ev['generated_at']} · model bundle `{ev['model_version']}` · "
        f"git `{ev.get('git_commit') or 'unknown'}`",
        "",
        "All results come from the simulator (synthetic data). Test episodes use seeds never seen in "
        "training or calibration. See *Limitations* at the end.",
        "",
        "## 1. Data",
        "",
        _table(
            ["split", "episodes", "rows", "seed range"],
            [
                [k, v["episodes"], v["rows"], f"{v['seeds'][0]}–{v['seeds'][1]}"]
                for k, v in ev["data"].items()
            ],
        ),
        "",
        "## 2. Failure-risk prediction (row level, test split)",
        "",
    ]
    pred = ev["predictive"]["risk"]
    for h, block in pred["horizons"].items():
        out.append(
            f"### Failure within {h} min — {block['positives']} positive of {block['rows']} rows "
            f"(prevalence {_fmt(block['prevalence'])})"
        )
        out.append("")
        rows = []
        for name, m in block["methods"].items():
            e = m["episode"]
            rows.append(
                [
                    name,
                    m["precision"],
                    m["recall"],
                    m["f1"],
                    m["pr_auc"],
                    m["false_positive_rate"],
                    m["brier"],
                    m["ece"],
                    f"{e['failing_detected']}/{e['failing_episodes']}",
                    e["lead_time_min_median"],
                    f"{e['healthy_episodes_with_alarm']}/{e['healthy_episodes']}",
                ]
            )
        out.append(
            _table(
                [
                    "method",
                    "precision",
                    "recall",
                    "F1",
                    "PR-AUC",
                    "FPR",
                    "Brier",
                    "ECE",
                    "failures alarmed",
                    "median lead (min)",
                    "healthy eps alarmed",
                ],
                rows,
            )
        )
        out.append("")
    out.append("Methods:")
    out += [f"- `{k}`: {v}" for k, v in pred["method_notes"].items()]
    out.append("")

    det = ev["predictive"]["detection"]
    out += [
        "## 3. Anomaly and change-point detection",
        "",
        _table(
            [
                "detector",
                "detected",
                "missed",
                "median delay (min)",
                "p90 delay",
                "pre-onset alarms",
                "healthy eps alarmed",
            ],
            [
                [
                    k,
                    f"{v['detected']}/{v['faulted_episodes']}",
                    v["missed"],
                    v["detection_delay_min_median"],
                    v["detection_delay_min_p90"],
                    v["episodes_with_pre_onset_alarm"],
                    f"{v['healthy_episodes_with_alarm']}/{v['healthy_episodes']}",
                ]
                for k, v in det.items()
                if isinstance(v, dict)
            ],
        ),
        "",
        det["notes"],
        "",
    ]

    dg = ev["predictive"]["diagnosis"]
    out += [
        "## 4. Fault diagnosis",
        "",
        _table(
            ["subset", "rows", "accuracy", "macro F1"],
            [
                [k, v["rows"], v["accuracy"], v["macro_f1"]]
                for k, v in dg.items()
                if isinstance(v, dict)
            ],
        ),
        "",
        f"Classes: {', '.join(dg['classes'])}. {dg['notes']}",
        "",
        f"Inference latency: p50 {_fmt(ev['predictive']['latency']['per_assessment_ms_p50'], 2)} ms, "
        f"p95 {_fmt(ev['predictive']['latency']['per_assessment_ms_p95'], 2)} ms "
        f"({ev['predictive']['latency']['scope']}).",
        "",
    ]

    iv = ev["interventions"]
    out += ["## 5. Closed-loop intervention outcomes", ""]
    out += _closed_loop(iv)
    conf = ev.get("interventions_confirmation")
    if conf:
        out += ["### 5.1 Confirmation on further test seeds", "", conf.get("note", ""), ""]
        out += _closed_loop(conf, notes=False)
    holdout = ev.get("interventions_holdout")
    if holdout:
        out += ["### 5.2 Final hold-out seeds", "", holdout.get("note", ""), ""]
        out += _closed_loop(holdout, notes=False)
    cf = ev.get("counterfactual")
    if cf:
        out += _counterfactual_section(cf)

    ag = ev["agent"]
    out += ["## 7. Agent reliability", ""]
    out += _agent_section(ag)
    out += ["", "## 8. Limitations", ""]
    out += [f"- {x}" for x in ev["limitations"]]
    out.append("")
    return "\n".join(out)


def _counterfactual_section(cf: dict) -> list[str]:
    out = [
        "## 6. Counterfactual calibration",
        "",
        f"{cf['decision_points']} held-out decision points (seeds {cf['seeds'][0]}–"
        f"{cf['seeds'][-1]}, minutes {', '.join(map(str, cf['decision_minutes']))}, no "
        f"intervention applied yet). At each point the planner's estimated-state ensemble "
        f"({cf['members']} members, {cf['horizon_min']:.0f}-min horizon) predicts the outcome of "
        f"each action ({', '.join(cf['actions'])}). Reference: {cf['reference']}",
        "",
        "`fixed` is the trend spread the planner and verifier use; `standard_error` widens each "
        "trend's spread to the standard error of its fit (used by the information gate's "
        "safety-of-waiting check).",
        "",
    ]
    header = [
        "uncertainty model",
        "branches",
        "Brier",
        "Brier (true state)",
        "Brier (base rate)",
        "predicted safe → true failures",
        "peak-T p10–p90 coverage",
        "peak-T median |error| (K)",
        "objective-best action = true best",
        "decision regret mean / max ($)",
    ]
    rows = []
    for mode, block in cf["modes"].items():
        o = block["overall"]
        rows.append(
            [
                mode,
                o["branches"],
                o["brier"],
                o["brier_reference_state"],
                o["brier_base_rate"],
                f"{o['false_safe_branches']}/{o['predicted_safe_branches']}",
                o["peak_temperature_p10_p90_coverage"],
                o["peak_temperature_median_abs_error_k"],
                f"{o['decision_matches_reference_best']}/{o['decisions']}",
                f"{_fmt(o['decision_regret_mean_usd'], 1)} / {_fmt(o['decision_regret_max_usd'], 1)}",
            ]
        )
    out += [_table(header, rows), "", "By scenario (`fixed`):", ""]
    fixed = cf["modes"]["fixed"]["by_scenario"]
    out.append(
        _table(
            [
                "scenario",
                "Brier",
                "predicted safe → true failures",
                "peak-T coverage",
                "peak-T bias (K)",
                "decision regret mean ($)",
            ],
            [
                [
                    s,
                    v.get("brier"),
                    f"{v.get('false_safe_branches')}/{v.get('predicted_safe_branches')}",
                    v.get("peak_temperature_p10_p90_coverage"),
                    v.get("peak_temperature_median_bias_k"),
                    v.get("decision_regret_mean_usd"),
                ]
                for s, v in fixed.items()
            ],
        )
    )
    by_state = cf["modes"]["fixed"].get("by_fault_state")
    if by_state:
        out += [
            "",
            "By fault state at the decision point (`fixed`). *Latent* means the fault is scheduled "
            "but has not started, so no telemetry can reveal it yet; *active* is the fair test of "
            "the estimator:",
            "",
            _table(
                [
                    "fault state",
                    "decision points",
                    "Brier",
                    "predicted safe → true failures",
                    "peak-T coverage",
                    "peak-T median |error| (K)",
                    "decision regret mean ($)",
                ],
                [
                    [
                        s,
                        v.get("decisions"),
                        v.get("brier"),
                        f"{v.get('false_safe_branches')}/{v.get('predicted_safe_branches')}",
                        v.get("peak_temperature_p10_p90_coverage"),
                        v.get("peak_temperature_median_abs_error_k"),
                        v.get("decision_regret_mean_usd"),
                    ]
                    for s, v in by_state.items()
                    if v
                ],
            ),
        ]
    for mode, block in cf["modes"].items():
        cases = block.get("false_safe_cases") or []
        if cases:
            out += ["", f"Predicted-safe branches that fail in the true process (`{mode}`):", ""]
            out += [
                f"- {c['case']} · {c['action']} · true failure rate {c['true_failure_rate']:.2f}"
                + (
                    f" · fault {c['fault_state']} (onset {c['fault_onset_min']:.0f} min)"
                    if c.get("fault_state") and c.get("fault_onset_min") is not None
                    else ""
                )
                for c in cases
            ]
    out += [
        "",
        "'Predicted safe → true failures' counts branches where the estimated ensemble shows no "
        "failure (what the verifier's failure_risk check requires) but some true-process "
        "realisations fail. The Brier score is computed against every true-process realisation; "
        "'true state' is the irreducible score of a predictor that knows the hidden state. Peak-T "
        "coverage is the share of true realisations whose peak winding temperature falls inside "
        "the ensemble's 10–90 % band (nominal 0.8). Decision regret prices the estimated "
        "ensemble's lowest-objective action under the true-state reference (not verifier-gated).",
        "",
    ]
    return out


def _closed_loop(iv: dict, notes: bool = True) -> list[str]:
    out = [
        f"{len(iv['scenarios'])} scenarios × {len(iv['seeds'])} held-out seeds "
        f"({iv['seeds'][0]}–{iv['seeds'][-1]}) × {iv['episode_hours']:.0f} h per episode. "
        f"{iv['approval_note']}",
        "",
    ]
    rows = []
    for p, b in iv["by_policy"].items():
        o = b["overall"]
        pv = iv["paired_vs_no_action"].get(p, {})
        rows.append(
            [
                p,
                f"{o['failures']}/{o['episodes']}",
                f"{o['failure_rate_ci95'][0]:.2f}–{o['failure_rate_ci95'][1]:.2f}",
                o["cost_mean"],
                pv.get("mean_cost_change_vs_no_action"),
                o["downtime_h_mean"],
                o["interventions_mean"],
                b["healthy_episodes_with_intervention"],
            ]
        )
    out.append(
        _table(
            [
                "policy",
                "failures",
                "95% CI",
                "mean cost ($)",
                "Δ cost vs none",
                "downtime (h)",
                "interventions",
                "healthy eps touched",
            ],
            rows,
        )
    )
    out += ["", "Failures by scenario:", ""]
    scen = iv["scenarios"]
    out.append(
        _table(
            ["policy", *scen],
            [
                [
                    p,
                    *[
                        f"{b['by_scenario'][s]['failures']}/{b['by_scenario'][s]['episodes']}"
                        for s in scen
                    ],
                ]
                for p, b in iv["by_policy"].items()
            ],
        )
    )
    out += ["", "Mean cost by scenario ($):", ""]
    out.append(
        _table(
            ["policy", *scen],
            [
                [p, *[b["by_scenario"][s]["cost_mean"] for s in scen]]
                for p, b in iv["by_policy"].items()
            ],
        )
    )
    if notes:
        out += ["", "Policies:"]
        out += [f"- `{k}`: {v}" for k, v in iv["policy_notes"].items()]
    out.append("")
    return out


def _agent_section(ag: dict) -> list[str]:
    out: list[str] = []
    d = ag["deterministic"]
    if d.get("runs"):
        out.append(
            _table(
                [
                    "provider",
                    "runs",
                    "completed",
                    "recommended",
                    "tool success",
                    "invalid actions",
                    "verifier rejections",
                    "latency p50/p95 (ms)",
                    "cost ($)",
                ],
                [
                    [
                        d["provider"],
                        d["runs"],
                        d["completion_rate"],
                        d["recommendation_rate"],
                        d["tool_success_rate"],
                        d["invalid_actions"],
                        d["verifier_rejections"],
                        f"{_fmt(d['latency_ms']['p50'])}/{_fmt(d['latency_ms']['p95'])}",
                        d["estimated_cost_usd"],
                    ]
                ],
            )
        )
    live = ag["live"]
    out.append("")
    if live.get("status") == "run" and live.get("arms"):
        out += _live_arms_section(live)
    elif live.get("status") == "run":
        out.append(
            f"Live Meta model (`{live['model']}`): {live['runs']} runs, completion "
            f"{_fmt(live['completion_rate'])}, tool success {_fmt(live['tool_success_rate'])}, "
            f"invalid actions {live['invalid_actions']}, verifier rejections "
            f"{live['verifier_rejections']}, hallucinated evidence ids "
            f"{live['hallucinated_evidence_ids']}, fallbacks {live['fallbacks']}, latency p50 "
            f"{_fmt(live['latency_ms']['p50'])} ms, tokens {live['input_tokens']} in / "
            f"{live['output_tokens']} out, estimated cost ${live['estimated_cost_usd']:.4f}."
        )
        if live.get("generated_at"):
            out.append(
                f"Live runs generated {live['generated_at']} · git `{live.get('git_commit')}`."
            )
        if live.get("audited_runs"):
            out.append(
                f"Regret audit ({live['audited_runs']} runs): mean regret vs deterministic planner "
                f"${live['mean_regret_vs_planner_usd']:.1f}; agent worse in "
                f"{live['runs_worse_than_planner']}, better in {live['runs_better_than_planner']}."
            )
        out += [
            "",
            _table(
                [
                    "case",
                    "status",
                    "agent action",
                    "planner action",
                    "regret ($)",
                    "rejections",
                    "tool calls",
                    "latency (s)",
                ],
                [
                    [
                        r["case"],
                        r["status"],
                        r["action"],
                        r.get("planner_action"),
                        (r.get("audit") or {}).get("regret_vs_planner"),
                        r["rejections"],
                        r["tool_calls"],
                        round(r["latency_ms"] / 1000, 1),
                    ]
                    for r in live.get("runs_detail", [])
                ],
            ),
            "",
            "Regret: agent branch objective minus planner branch objective in one shared audit "
            "comparison (same estimated state and seeds; positive means the agent's choice is "
            "worse under the simulator's cost model).",
        ]
    else:
        out.append(f"Live model evaluation: **not run** — {live.get('reason')}")
    for key, title in (
        ("live_recheck", "Re-check after verifier fixes"),
        ("live_v4", "Re-check on verifier v4 with the information gate"),
    ):
        block = ag.get(key) or {}
        if block.get("status") == "run" and block.get("arms"):
            out += ["", f"### {title}", ""]
            out += _live_arms_section(block)
    return out
