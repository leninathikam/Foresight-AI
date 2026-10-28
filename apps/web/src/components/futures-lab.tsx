"use client";

import Link from "next/link";
import { useState } from "react";
import { api } from "@/lib/api";
import { describeAction, num, pct, signed, simClock, usd } from "@/lib/format";
import { useSession } from "@/lib/session-context";
import type { Action, BranchOutcome, FutureComparison, VerificationResult } from "@/lib/types";
import { BRANCH_COLORS, BranchBandChart } from "./charts";
import { Badge, Button, Card, EmptyState, Field, Notice, PageHeader, ProvenanceTag, Segmented, Spinner, cx, inputClass } from "./ui";
import { VerificationView } from "./verification-view";

interface Candidate {
  key: string;
  enabled: boolean;
  action: Action;
}

const DEFAULT_CANDIDATES: Candidate[] = [
  { key: "load", enabled: true, action: { type: "reduce_load", fraction: 0.3 } },
  { key: "speed", enabled: true, action: { type: "reduce_speed", fraction: 0.3 } },
  { key: "cool", enabled: true, action: { type: "increase_cooling", boost: 0.4 } },
  { key: "inspect", enabled: true, action: { type: "schedule_inspection", delay_minutes: 10 } },
  { key: "stop", enabled: false, action: { type: "controlled_shutdown" } },
];

function ParamInput({ action, onChange }: { action: Action; onChange: (a: Action) => void }) {
  const cls = cx(inputClass, "w-20 py-1 text-xs");
  switch (action.type) {
    case "reduce_load":
    case "reduce_speed":
      return (
        <input
          type="number"
          step={5}
          className={cls}
          value={Math.round(action.fraction * 100)}
          onChange={(e) => onChange({ ...action, fraction: Number(e.target.value) / 100 })}
          aria-label="percent"
        />
      );
    case "increase_cooling":
      return (
        <input
          type="number"
          step={5}
          className={cls}
          value={Math.round(action.boost * 100)}
          onChange={(e) => onChange({ ...action, boost: Number(e.target.value) / 100 })}
          aria-label="percent airflow"
        />
      );
    case "schedule_inspection":
      return (
        <input
          type="number"
          step={5}
          className={cls}
          value={action.delay_minutes}
          onChange={(e) => onChange({ ...action, delay_minutes: Number(e.target.value) })}
          aria-label="delay minutes"
        />
      );
    default:
      return null;
  }
}

function BranchRow({
  b,
  color,
  best,
  selected,
  onSelect,
}: {
  b: BranchOutcome;
  color: string;
  best: boolean;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <tr
      onClick={onSelect}
      className={cx(
        "cursor-pointer border-t border-slate-800 text-[12px] transition-colors",
        selected ? "bg-slate-800/60" : "hover:bg-slate-800/30",
      )}
    >
      <td className="relative py-2.5 pl-5">
        {selected && <span className="absolute inset-y-0 left-0 w-[2px] bg-slate-100" />}
        <span className="mr-2.5 inline-block h-[3px] w-3 align-middle" style={{ background: color }} />
        <span className="text-slate-100">{b.label}</span>
        {b.branch_id === "baseline" && <span className="ml-1.5 text-slate-500">no action</span>}
        {best && <span className="ml-2"><Badge tone="cyan">Best</Badge></span>}
      </td>
      <td className="py-2 text-right font-mono tabular-nums">
        <span className={b.failure_incidence > 0 ? "text-rose-300" : "text-emerald-300"}>
          {pct(b.failure_incidence)}
        </span>
        <span className="block text-[10px] text-slate-500">
          CI {pct(b.failure_incidence_ci95[0])}–{pct(b.failure_incidence_ci95[1])}
        </span>
      </td>
      <td className="py-2 text-right font-mono tabular-nums text-slate-300">
        {b.median_time_to_failure_min === null ? "—" : `${num(b.median_time_to_failure_min, 0)} min`}
      </td>
      <td className="py-2 text-right font-mono tabular-nums text-slate-300">{num(b.peak_temperature_p90_c, 1)}</td>
      <td className="py-2 text-right font-mono tabular-nums text-slate-300">{num(b.peak_vibration_p90_mm_s, 2)}</td>
      <td className="py-2 text-right font-mono tabular-nums text-slate-300">{num(b.downtime_mean_h, 2)} h</td>
      <td className="py-2.5 pr-5 text-right font-mono tabular-nums text-slate-100">
        {usd(b.objective)}
        {b.branch_id !== "baseline" && (
          <span className="block text-[10px] text-slate-500">{signed(b.delta_vs_baseline.objective, 0)} vs none</span>
        )}
      </td>
    </tr>
  );
}

export function FuturesLab() {
  const { state } = useSession();
  const [candidates, setCandidates] = useState(DEFAULT_CANDIDATES);
  const [horizon, setHorizon] = useState(180);
  const [members, setMembers] = useState(8);
  const [source, setSource] = useState<"estimated" | "oracle">("estimated");
  const [comparison, setComparison] = useState<FutureComparison | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [metric, setMetric] = useState<"temperature" | "vibration">("temperature");
  const [verification, setVerification] = useState<VerificationResult | null>(null);
  const [approve, setApprove] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [applied, setApplied] = useState<string | null>(null);

  const id = state.sessionId;
  if (!id || !state.status) {
    return (
      <EmptyState
        eyebrow="02 / Future Branching"
        title="No live session"
        action={
          <Link href="/" className="inline-flex h-9 items-center rounded-[5px] bg-slate-50 px-4 text-[13px] font-medium text-slate-950 hover:bg-white">
            Go to Mission Control
          </Link>
        }
      >
        Futures branch from the current state of a running digital twin. Start a session first,
        then compare interventions side by side.
      </EmptyState>
    );
  }

  const guard = async (label: string, fn: () => Promise<void>) => {
    setBusy(label);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  const runFutures = () =>
    guard("futures", async () => {
      const actions = candidates.filter((c) => c.enabled).map((c) => c.action);
      if (!actions.length) throw new Error("Select at least one candidate action");
      const comp = await api.futures(id, { actions, horizon_min: horizon, members, state_source: source });
      setComparison(comp);
      setSelected(comp.ranking[0] ?? null);
      setVerification(null);
      setApprove(false);
      setApplied(null);
    });

  const selectedBranch = comparison?.branches.find((b) => b.branch_id === selected) ?? null;

  const runVerify = () =>
    guard("verify", async () => {
      if (!comparison || !selectedBranch) return;
      setVerification(await api.verify(id, selectedBranch.action, comparison.id));
      setApprove(false);
    });

  const apply = () =>
    guard("apply", async () => {
      if (!comparison || !selectedBranch) return;
      const res = await api.intervene(id, {
        action: selectedBranch.action,
        approved: approve,
        source: "user",
        comparison_id: comparison.id,
      });
      setApplied(res.event.summary);
    });

  const est = comparison?.estimate;
  return (
    <div className="space-y-6">
      <PageHeader
        index="02"
        section="Future Branching"
        title="Compare futures before acting"
        description="Every branch starts from the same machine state and uses the same disturbance seeds (common random numbers), so differences come from the intervention, not from noise. Outcomes are simulation estimates under the twin's documented assumptions."
      />
      {error && <Notice tone="rose">{error}</Notice>}

      <Card title="Candidate interventions" subtitle={`Branch from T+${simClock(state.status.sim_time_s)} · a no-action baseline is always included`}>
        <div className="flex flex-wrap gap-2">
          {candidates.map((c, i) => (
            <label
              key={c.key}
              className={cx(
                "flex h-10 cursor-pointer items-center gap-2.5 rounded-[5px] border px-3 text-[13px] transition-colors",
                c.enabled ? "border-slate-500 bg-slate-800/60 text-slate-100" : "border-slate-800 text-slate-500 hover:border-slate-700",
              )}
            >
              <input
                type="checkbox"
                className="accent-slate-100"
                checked={c.enabled}
                onChange={(e) =>
                  setCandidates((cs) => cs.map((x, j) => (j === i ? { ...x, enabled: e.target.checked } : x)))
                }
              />
              <span>{describeAction(c.action)}</span>
              <ParamInput
                action={c.action}
                onChange={(a) => setCandidates((cs) => cs.map((x, j) => (j === i ? { ...x, action: a } : x)))}
              />
            </label>
          ))}
        </div>
        <div className="mt-5 flex flex-wrap items-end gap-5 border-t border-slate-800 pt-5">
          <Field label="Horizon (min)">
            <input type="number" min={30} max={360} step={30} value={horizon} onChange={(e) => setHorizon(Number(e.target.value))} className={cx(inputClass, "w-24")} />
          </Field>
          <Field label="Ensemble members">
            <input type="number" min={4} max={32} value={members} onChange={(e) => setMembers(Number(e.target.value))} className={cx(inputClass, "w-24")} />
          </Field>
          <Field label="Initial state">
            <select value={source} onChange={(e) => setSource(e.target.value as "estimated" | "oracle")} className={inputClass}>
              <option value="estimated">Estimated from telemetry (default)</option>
              <option value="oracle">Oracle: hidden true state (upper bound, for evaluation)</option>
            </select>
          </Field>
          <Button variant="primary" onClick={runFutures} disabled={busy !== null}>
            {busy === "futures" && <Spinner />} Simulate futures
          </Button>
        </div>
      </Card>

      {comparison && (
        <>
          {comparison.state_source === "oracle" && (
            <Notice tone="amber">
              These branches start from the simulator&apos;s hidden true state. That&apos;s
              useful as an upper bound, but a real deployment could never do it.
            </Notice>
          )}
          <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_400px]">
            <Card
              title="Branch outcomes"
              subtitle={`${comparison.n_members} members × ${comparison.horizon_min} min · computed in ${(comparison.compute_ms / 1000).toFixed(1)} s · ${comparison.id}`}
              actions={<ProvenanceTag kind="simulation_estimate" />}
              flush
            >
              <div className="overflow-x-auto">
                <table className="w-full min-w-[720px]">
                  <thead>
                    <tr className="text-left font-mono text-[10.5px] uppercase tracking-[0.08em] text-slate-500">
                      <th className="py-2.5 pl-5 font-medium">Branch</th>
                      <th className="py-2.5 text-right font-medium">Failure</th>
                      <th className="py-2.5 text-right font-medium">Median TTF</th>
                      <th className="py-2.5 text-right font-medium">Peak T p90</th>
                      <th className="py-2.5 text-right font-medium">Peak vib p90</th>
                      <th className="py-2.5 text-right font-medium">Downtime</th>
                      <th className="py-2.5 pr-5 text-right font-medium">Objective</th>
                    </tr>
                  </thead>
                  <tbody>
                    {comparison.branches.map((b, i) => (
                      <BranchRow
                        key={b.branch_id}
                        b={b}
                        color={BRANCH_COLORS[i % BRANCH_COLORS.length]}
                        best={comparison.ranking[0] === b.branch_id}
                        selected={selected === b.branch_id}
                        onSelect={() => {
                          setSelected(b.branch_id);
                          setVerification(null);
                          setApprove(false);
                        }}
                      />
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="border-t border-slate-800 px-5 pb-5 pt-4">
              <div className="mb-3 flex items-center justify-between gap-4">
                <span className="text-[12px] text-slate-400">Median trajectory per branch · shaded band is p10–p90 of the selected branch</span>
                <Segmented options={["temperature", "vibration"] as const} value={metric} onChange={setMetric} />
              </div>
              <BranchBandChart branches={comparison.branches} selected={selected} metric={metric} />
              <details className="mt-4 text-[12px] text-slate-400">
                <summary className="cursor-pointer font-mono text-[10.5px] uppercase tracking-[0.08em] text-slate-500 hover:text-slate-300">Objective and assumptions</summary>
                <p className="mt-2">{comparison.objective_definition}</p>
                <ul className="mt-2 list-disc space-y-1 pl-5">
                  {comparison.assumptions.map((a) => (
                    <li key={a}>{a}</li>
                  ))}
                </ul>
              </details>
              </div>
            </Card>

            <div className="space-y-6">
              {selectedBranch && (
                <Card
                  title={selectedBranch.label}
                  subtitle="Verify before applying. The verifier is deterministic and independent of the ranking."
                >
                  <dl className="mb-3 grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
                    {Object.entries(selectedBranch.cost_breakdown_mean).map(([k, v]) => (
                      <div key={k} className="contents">
                        <dt className="text-slate-500">{k.replaceAll("_", " ")}</dt>
                        <dd className="text-right font-mono tabular-nums text-slate-300">{usd(v)}</dd>
                      </div>
                    ))}
                  </dl>
                  {selectedBranch.branch_id === "baseline" ? (
                    <p className="text-xs text-slate-500">The baseline is the no-action reference.</p>
                  ) : (
                    <div className="space-y-3">
                      <Button onClick={runVerify} disabled={busy !== null}>
                        {busy === "verify" && <Spinner />} Run safety verifier
                      </Button>
                      {verification && <VerificationView v={verification} />}
                      {verification && verification.verdict !== "rejected" && !applied && (
                        <div className="space-y-3 rounded-[5px] border border-slate-700 bg-slate-950 p-4">
                          <label className="flex items-start gap-2.5 text-[12px] text-slate-300">
                            <input type="checkbox" checked={approve} onChange={(e) => setApprove(e.target.checked)} className="mt-0.5 accent-slate-100" />
                            I approve applying &ldquo;{selectedBranch.label}&rdquo; to the simulated machine.
                          </label>
                          <Button variant="primary" onClick={apply} disabled={!approve || busy !== null}>
                            {busy === "apply" && <Spinner />} Apply approved action
                          </Button>
                        </div>
                      )}
                      {applied && <Notice tone="emerald">Applied: {applied}. It was re-verified against this comparison before execution.</Notice>}
                    </div>
                  )}
                </Card>
              )}
              {est && (
                <Card title="Estimated machine state" subtitle={est.method} actions={<ProvenanceTag kind="simulation_estimate" />}>
                  <dl className="grid grid-cols-2 gap-x-3 gap-y-1.5 text-xs">
                    <dt className="text-slate-500">Cooling efficiency</dt>
                    <dd className="text-right font-mono tabular-nums">{num(est.cooling_efficiency, 2)} ± {num(est.cooling_efficiency_std, 2)}</dd>
                    <dt className="text-slate-500">Cooling trend</dt>
                    <dd className="text-right font-mono tabular-nums">{signed(est.cooling_trend_per_h, 2)} /h</dd>
                    <dt className="text-slate-500">Bearing damage</dt>
                    <dd className="text-right font-mono tabular-nums">{num(est.bearing_damage, 2)} ± {num(est.bearing_damage_std, 2)}</dd>
                    <dt className="text-slate-500">Damage growth</dt>
                    <dd className="text-right font-mono tabular-nums">{num(est.bearing_growth_per_h, 2)} /h</dd>
                    <dt className="text-slate-500">Process load</dt>
                    <dd className="text-right font-mono tabular-nums">{num(est.process_load, 2)} (baseline {num(est.baseline_process_load, 2)})</dd>
                    <dt className="text-slate-500">Load trend</dt>
                    <dd className="text-right font-mono tabular-nums">{signed(est.load_trend_per_h, 2)} /h</dd>
                  </dl>
                  {est.notes.length > 0 && (
                    <ul className="mt-2 list-disc space-y-0.5 pl-4 text-[11px] text-slate-500">
                      {est.notes.map((n) => (
                        <li key={n}>{n}</li>
                      ))}
                    </ul>
                  )}
                </Card>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
