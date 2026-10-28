import type { VerificationResult } from "@/lib/types";
import { Badge, ProvenanceTag, cx } from "./ui";

const LABELS: Record<string, string> = {
  action_parameters_valid: "Action parameters within policy",
  simulation_complete: "Simulation complete and fresh",
  intervention_feasible: "Intervention feasible in time",
  temperature_limit: "Winding temperature limit",
  vibration_limit: "Vibration limit",
  load_range: "Load within rated range",
  failure_risk: "No simulated failures",
  uncertainty: "Uncertainty acceptable",
  improves_on_baseline: "Improves on no-action",
  independent_confirmation: "Independent re-simulation",
  evidence_exists: "Cited evidence exists",
  evidence_consistency: "Claim consistent with evidence",
};

const STATUS = {
  pass: { mark: "PASS", cls: "text-emerald-300" },
  warn: { mark: "WARN", cls: "text-amber-300" },
  fail: { mark: "FAIL", cls: "text-rose-300" },
  skip: { mark: "N/A", cls: "text-slate-600" },
} as const;

export function VerificationView({ v }: { v: VerificationResult }) {
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={v.verdict === "rejected" ? "rose" : v.verdict === "accepted" ? "emerald" : "amber"}>
          {v.verdict.replaceAll("_", " ")}
        </Badge>
        {v.requires_human_approval && <Badge tone="slate">Needs human approval</Badge>}
        {v.verdict !== "rejected" && (
          <span className="ml-auto">
            <ProvenanceTag kind="verified" />
          </span>
        )}
      </div>
      <p className="text-[12px] leading-relaxed text-slate-400">{v.summary}</p>
      <ul className="divide-y divide-slate-800 border-y border-slate-800">
        {v.checks.map((c, i) => {
          const st = STATUS[c.status as keyof typeof STATUS] ?? STATUS.skip;
          return (
            <li key={`${c.name}-${i}`} className="grid grid-cols-[2.75rem_minmax(0,1fr)] gap-x-3 py-2 text-[12px]">
              <span
                className={cx("pt-px font-mono text-[10px] font-medium tracking-[0.08em]", st.cls)}
                title={c.status === "skip" ? "Not applicable" : undefined}
              >
                {st.mark}
              </span>
              <span className="min-w-0">
                <span className="flex flex-wrap items-baseline justify-between gap-x-3">
                  <span className={c.status === "skip" ? "text-slate-500" : "text-slate-200"}>
                    {LABELS[c.name] ?? c.name}
                  </span>
                  {c.measured !== null && c.limit !== null && (
                    <span className="font-mono text-[11px] tabular-nums text-slate-500">
                      {typeof c.measured === "number" ? c.measured.toFixed(2) : c.measured}
                      <span className="mx-1 text-slate-700">/</span>
                      {typeof c.limit === "number" ? c.limit.toFixed(2) : c.limit}
                    </span>
                  )}
                </span>
                <span className="mt-0.5 block leading-relaxed text-slate-500">{c.detail}</span>
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
