"use client";

import { useState } from "react";
import type { CheckResult, VerificationResult } from "@/lib/types";
import { Badge, ProvenanceTag, cx } from "./ui";

const LABELS: Record<string, string> = {
  action_parameters_valid: "Action parameters within envelope",
  simulation_complete: "Simulation complete and fresh",
  intervention_feasible: "Intervention feasible in time",
  temperature_limit: "Peak winding temperature limit",
  vibration_limit: "Peak vibration velocity limit",
  vibration_trajectory: "Full vibration trajectory (ISO 10816-3)",
  load_range: "Load within rated continuous limit",
  failure_risk: "Simulated failure elimination",
  uncertainty: "Counterfactual uncertainty bound",
  improves_on_baseline: "Strict improvement over do-nothing",
  independent_confirmation: "Fresh Monte Carlo re-simulation",
  evidence_exists: "Evidence provenance and existence",
  evidence_consistency: "Claimed mode consistent with telemetry",
};

const CATEGORIES = [
  {
    title: "1. Physical Operating Envelope & ISO Standards",
    checks: ["temperature_limit", "vibration_limit", "vibration_trajectory", "load_range"],
  },
  {
    title: "2. Action Feasibility & Simulation Integrity",
    checks: ["action_parameters_valid", "intervention_feasible", "simulation_complete"],
  },
  {
    title: "3. Counterfactual Proof & Statistical Confirmation",
    checks: ["failure_risk", "improves_on_baseline", "independent_confirmation", "uncertainty"],
  },
  {
    title: "4. Evidence Provenance & Diagnostic Consistency",
    checks: ["evidence_exists", "evidence_consistency"],
  },
];

const STATUS = {
  pass: { mark: "PASS", cls: "text-emerald-400 bg-emerald-500/10 border-emerald-500/20" },
  warn: { mark: "WARN", cls: "text-amber-400 bg-amber-500/10 border-amber-500/20" },
  fail: { mark: "FAIL", cls: "text-rose-400 bg-rose-500/10 border-rose-500/20" },
  skip: { mark: "N/A", cls: "text-slate-500 bg-slate-800/40 border-slate-700/30" },
} as const;

export function VerificationView({ v }: { v: VerificationResult }) {
  const [copied, setCopied] = useState(false);

  const copyHash = () => {
    if (v.decision_hash) {
      navigator.clipboard.writeText(v.decision_hash);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  const checksByName = new Map<string, CheckResult>();
  v.checks.forEach((c) => checksByName.set(c.name, c));

  return (
    <div className="space-y-4 rounded-lg border border-slate-800 bg-slate-950/40 p-4">
      {/* Formal Header */}
      <div className="border-b border-slate-800/80 pb-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <span className="font-mono text-[11px] font-semibold tracking-wider text-slate-400 uppercase">
              Safety Verifier v5 Proof Explorer
            </span>
            <Badge tone="slate">ISO 10816-3 Group 2</Badge>
          </div>
          <div className="flex items-center gap-2">
            <Badge tone={v.verdict === "rejected" ? "rose" : v.verdict === "accepted" ? "emerald" : "amber"}>
              {v.verdict.toUpperCase().replaceAll("_", " ")}
            </Badge>
            <ProvenanceTag kind="verified" />
          </div>
        </div>

        {/* Cryptographic Decision Hash */}
        {v.decision_hash && (
          <div className="mt-2.5 flex items-center justify-between rounded bg-slate-900/60 px-2.5 py-1.5 text-[11px]">
            <div className="flex items-center gap-2 overflow-hidden font-mono text-slate-400">
              <span className="text-slate-500">SHA-256:</span>
              <span className="truncate text-slate-300">{v.decision_hash}</span>
            </div>
            <button
              onClick={copyHash}
              className="ml-2 shrink-0 font-mono text-[10px] text-cyan-400 hover:text-cyan-300"
            >
              {copied ? "COPIED" : "COPY PROOF"}
            </button>
          </div>
        )}

        <p className="mt-2 text-[12px] leading-relaxed text-slate-300">{v.summary}</p>
      </div>

      {/* Categorized Proof Checks */}
      <div className="space-y-4">
        {CATEGORIES.map((cat) => {
          const groupChecks = cat.checks
            .map((name) => checksByName.get(name))
            .filter((c): c is CheckResult => c !== undefined);

          if (groupChecks.length === 0) return null;

          return (
            <div key={cat.title} className="space-y-1.5">
              <h4 className="font-mono text-[10px] font-medium tracking-wider text-slate-400 uppercase">
                {cat.title}
              </h4>
              <div className="divide-y divide-slate-800/60 rounded border border-slate-800/80 bg-slate-900/20">
                {groupChecks.map((c) => {
                  const st = STATUS[c.status as keyof typeof STATUS] ?? STATUS.skip;
                  const hasLimit = c.measured !== null && c.limit !== null;

                  return (
                    <div key={c.name} className="p-2.5 text-[12px]">
                      <div className="flex items-start justify-between gap-3">
                        <div className="flex items-center gap-2">
                          <span
                            className={cx(
                              "inline-flex items-center justify-center rounded border px-1.5 py-0.5 font-mono text-[9px] font-bold tracking-wider",
                              st.cls,
                            )}
                          >
                            {st.mark}
                          </span>
                          <span className="font-medium text-slate-200">
                            {LABELS[c.name] ?? c.name}
                          </span>
                        </div>
                        {hasLimit && (
                          <div className="text-right font-mono text-[11px] tabular-nums">
                            <span className="text-slate-200">
                              {typeof c.measured === "number" ? c.measured.toFixed(2) : c.measured}
                            </span>
                            <span className="mx-1 text-slate-600">/</span>
                            <span className="text-slate-400">
                              {typeof c.limit === "number" ? c.limit.toFixed(2) : c.limit}
                            </span>
                          </div>
                        )}
                      </div>
                      <p className="mt-1 pl-8 text-[11px] leading-relaxed text-slate-400">
                        {c.detail}
                      </p>
                    </div>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>

      {/* Operator Gate Notification */}
      {v.requires_human_approval && (
        <div className="flex items-center justify-between rounded border border-emerald-900/30 bg-emerald-950/20 px-3 py-2 text-[11px] text-emerald-300">
          <span>Action passed independent verification. Operator confirmation required.</span>
          <span className="font-mono font-medium">FAIL-CLOSED GATE</span>
        </div>
      )}
    </div>
  );
}
