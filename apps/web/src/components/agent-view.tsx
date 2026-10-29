"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { num, pct, simClock, usd } from "@/lib/format";
import { useSession } from "@/lib/session-context";
import type {
  AgentStage,
  AgentTrace,
  EvidenceItem,
  InformationAssessment,
  ProviderInfo,
  ProviderName,
  TraceStep,
  TrendEvidence,
} from "@/lib/types";
import { Badge, Button, Card, EmptyState, Eyebrow, Notice, PageHeader, ProvenanceTag, Segmented, Spinner, cx, inputClass } from "./ui";
import { VerificationView } from "./verification-view";

const TREND_LABEL: Record<TrendEvidence["name"], string> = {
  cooling_fouling: "Cooling fouling",
  bearing_growth: "Bearing damage growth",
  load_ramp: "Load ramp",
};

function InformationGate({ info }: { info: InformationAssessment }) {
  const gather = info.decision === "gather_information";
  return (
    <div>
      <Eyebrow className="mb-2">Information gate</Eyebrow>
      <Notice tone={gather ? "amber" : "slate"}>
        <span className="font-medium text-slate-100">{gather ? `Gather ${num(info.defer_minutes, 0)} more minutes of data` : "Act now"}</span>
        {" · "}
        {info.reasons[0]}
      </Notice>
      <div className="mt-2 grid grid-cols-[minmax(0,1fr)_auto_auto_auto] gap-x-5 border-y border-slate-800 py-2 font-mono text-[10.5px] uppercase tracking-[0.08em] text-slate-500">
        <span>Fitted trend</span>
        <span className="text-right">per hour</span>
        <span className="text-right">t-stat</span>
        <span className="text-right">status</span>
      </div>
      {info.trends.map((t) => (
        <div key={t.name} className="grid grid-cols-[minmax(0,1fr)_auto_auto_auto] gap-x-5 border-b border-slate-800 py-2 text-[12px]">
          <span className={t.drives_forecast ? "text-slate-200" : "text-slate-500"}>{TREND_LABEL[t.name]}</span>
          <span className="text-right font-mono tabular-nums text-slate-300">
            {num(t.value_per_h, 3)}
            {t.se_per_h !== null ? ` ± ${num(t.se_per_h, 3)}` : ""}
          </span>
          <span className="text-right font-mono tabular-nums text-slate-300">{t.t_stat === null ? "n/a" : num(t.t_stat, 1)}</span>
          <span className="text-right">
            {!t.drives_forecast ? (
              <Badge tone="slate">inactive</Badge>
            ) : t.supported ? (
              <Badge tone="emerald">supported</Badge>
            ) : (
              <Badge tone="amber">weak</Badge>
            )}
          </span>
        </div>
      ))}
      {info.reasons.length > 1 && (
        <ul className="mt-2 space-y-1 text-[12px] leading-relaxed text-slate-400">
          {info.reasons.slice(1).map((r) => (
            <li key={r}>{r}</li>
          ))}
        </ul>
      )}
      <div className="mt-2"><ProvenanceTag kind="simulation_estimate" /></div>
    </div>
  );
}

const STAGES: AgentStage[] = ["OBSERVE", "ANALYZE", "HYPOTHESIZE", "INVESTIGATE", "SIMULATE", "VERIFY", "RECOMMEND", "DONE"];

function StageBar({ trace }: { trace: AgentTrace }) {
  const visited = new Set(trace.stage_history);
  const failed = trace.stage === "FAILED";
  return (
    <ol className="grid grid-cols-4 gap-px overflow-hidden rounded-[5px] border border-slate-800 bg-slate-800 sm:grid-cols-8">
      {STAGES.map((s, i) => {
        const current = trace.stage === s;
        const done = visited.has(s) && !current;
        const live = current && trace.status === "running";
        return (
          <li key={s} className="relative bg-slate-900 px-3 py-2.5">
            <span
              className={cx(
                "absolute inset-x-0 top-0 h-[2px]",
                live ? "bg-cyan-400" : current ? "bg-emerald-400" : done ? "bg-slate-500" : "bg-transparent",
              )}
            />
            <div className="font-mono text-[10px] text-slate-600">{String(i + 1).padStart(2, "0")}</div>
            <div
              className={cx(
                "mt-0.5 flex items-center gap-1.5 font-mono text-[10.5px] font-medium uppercase tracking-[0.08em]",
                live ? "text-cyan-300" : current ? "text-emerald-300" : done ? "text-slate-300" : "text-slate-600",
              )}
            >
              {live && <Spinner className="h-2.5 w-2.5" />}
              {s}
            </div>
          </li>
        );
      })}
      {failed && (
        <li className="col-span-full bg-slate-900 px-3 py-2">
          <Badge tone="rose">Failed</Badge>
        </li>
      )}
    </ol>
  );
}

const KIND_LABEL: Record<TraceStep["kind"], { label: string; tone: "cyan" | "violet" | "emerald" | "slate" | "rose" | "amber" }> = {
  tool_call: { label: "Tool", tone: "cyan" },
  llm_call: { label: "Model", tone: "violet" },
  verification: { label: "Verify", tone: "emerald" },
  transition: { label: "Stage", tone: "slate" },
  note: { label: "Note", tone: "amber" },
  error: { label: "Error", tone: "rose" },
};

function StepRow({ step }: { step: TraceStep }) {
  if (step.kind === "transition") {
    return (
      <li className="flex items-center gap-3 bg-slate-950/40 px-5 py-1.5 font-mono text-[10.5px] uppercase tracking-[0.08em] text-slate-600">
        <span className="w-8">{step.seq}</span>
        {step.name}
      </li>
    );
  }
  const k = KIND_LABEL[step.kind];
  return (
    <li className="grid grid-cols-[2rem_4.5rem_minmax(0,1fr)] gap-x-3 px-5 py-3 text-[12px]">
      <span className="font-mono text-slate-600">{step.seq}</span>
      <span className="pt-px">
        <Badge tone={step.ok ? k.tone : "rose"}>{step.ok ? k.label : "Error"}</Badge>
      </span>
      <div className="min-w-0">
        <div className="flex flex-wrap items-baseline gap-x-3">
          <span className="font-mono text-[12px] text-slate-100">{step.name}</span>
          <span className="ml-auto font-mono text-[10.5px] text-slate-600">
            {step.latency_ms > 0 && `${num(step.latency_ms, 0)} ms`}
            {step.input_tokens > 0 && ` · ${step.input_tokens}→${step.output_tokens} tok`}
          </span>
        </div>
        {step.result_summary && <p className="mt-1 leading-relaxed text-slate-400">{step.result_summary}</p>}
        {Object.keys(step.arguments).length > 0 && (
          <details className="mt-1.5">
            <summary className="cursor-pointer font-mono text-[10.5px] uppercase tracking-[0.08em] text-slate-600 hover:text-slate-400">
              Arguments
            </summary>
            <pre className="mt-1.5 overflow-x-auto rounded-[4px] border border-slate-800 bg-slate-950 p-2.5 font-mono text-[11px] text-slate-400">
              {JSON.stringify(step.arguments, null, 2)}
            </pre>
          </details>
        )}
      </div>
    </li>
  );
}

function EvidenceList({ items }: { items: EvidenceItem[] }) {
  return (
    <ul className="divide-y divide-slate-800">
      {items.map((e) => (
        <li key={e.id} className="flex items-center gap-3 py-1.5 text-[12px]">
          <ProvenanceTag kind={e.kind} />
          <span className="font-mono text-slate-500">{e.id}</span>
          <span className="ml-auto font-mono tabular-nums text-slate-300">
            {num(e.value, 3)} {e.unit}
          </span>
        </li>
      ))}
    </ul>
  );
}

export function AgentView() {
  const { state, noteAgentRun } = useSession();
  const [localRunId, setLocalRunId] = useState<string | null>(null);
  const [trace, setTrace] = useState<AgentTrace | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [approve, setApprove] = useState(false);
  const [applying, setApplying] = useState(false);
  const [applied, setApplied] = useState<string | null>(null);
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [provider, setProvider] = useState<ProviderName | null>(null);
  const [effort, setEffort] = useState<string>("");

  useEffect(() => {
    let cancelled = false;
    api
      .diagnostics()
      .then((d) => {
        if (cancelled) return;
        const usable = d.providers.filter((p) => p.configured);
        const initial = usable.find((p) => p.default) ?? usable[0];
        setProviders(usable);
        if (initial) {
          setProvider(initial.name);
          setEffort(initial.efforts.includes(d.llm.reasoning_effort) ? d.llm.reasoning_effort : initial.efforts[0]);
        }
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  const selected = providers.find((p) => p.name === provider);
  const chooseProvider = (name: ProviderName) => {
    setProvider(name);
    const efforts = providers.find((p) => p.name === name)?.efforts ?? [];
    if (!efforts.includes(effort)) setEffort(efforts.includes("medium") ? "medium" : efforts[0]);
  };

  const sessionId = state.sessionId;
  const runId = localRunId ?? state.latestRunId;
  const progressSteps = runId ? state.agent[runId]?.steps : undefined;

  useEffect(() => {
    if (!sessionId || !runId) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const load = async () => {
      try {
        const t = await api.agentRun(sessionId, runId);
        if (cancelled) return;
        setTrace(t);
        if (t.status === "running") timer = setTimeout(load, 1000);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      }
    };
    void load();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [sessionId, runId, progressSteps]);

  if (!sessionId || !state.status) {
    return (
      <EmptyState
        eyebrow="03 / Agent"
        title="No live session"
        action={
          <Link href="/" className="inline-flex h-9 items-center rounded-[5px] bg-slate-50 px-4 text-[13px] font-medium text-slate-950 hover:bg-white">
            Go to Mission Control
          </Link>
        }
      >
        The agent investigates a running digital twin. Start a session, inject a fault, and let the
        risk build before running an analysis.
      </EmptyState>
    );
  }

  const start = async () => {
    setStarting(true);
    setError(null);
    setApplied(null);
    setApprove(false);
    try {
      const res = await api.startAgent(
        sessionId,
        provider ? { provider, reasoning_effort: effort || undefined } : undefined,
      );
      noteAgentRun(res.run_id);
      setLocalRunId(res.run_id);
      setTrace(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setStarting(false);
    }
  };

  const rec = trace?.recommendation;
  const applyRecommendation = async () => {
    if (!rec?.action || !rec.comparison_id) return;
    setApplying(true);
    setError(null);
    try {
      const res = await api.intervene(sessionId, {
        action: rec.action,
        approved: approve,
        source: "agent",
        comparison_id: rec.comparison_id,
      });
      setApplied(res.event.summary);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setApplying(false);
    }
  };

  const running = trace?.status === "running";
  return (
    <div className="space-y-6">
      <PageHeader
        index="03"
        section="Agent"
        title="Agent investigation"
        description="A bounded state machine that observes, analyzes, forms hypotheses, investigates with tools, simulates futures, and verifies before it recommends. The model can only call the listed tools, every number comes from a tool result, and nothing is applied without your approval."
        actions={
          <div className="flex flex-wrap items-center gap-3">
            {providers.length > 0 && provider && (
              <>
                <Segmented
                  options={providers.map((p) => p.name)}
                  value={provider}
                  onChange={chooseProvider}
                  format={(n) => (n === "meta" ? "Meta · Muse Spark 1.3" : "Fireworks · Muse Spark Open")}
                />
                <label className="flex items-center gap-2">
                  <Eyebrow>Effort</Eyebrow>
                  <select
                    className={cx(inputClass, "h-7 font-mono text-[11px]")}
                    value={effort}
                    onChange={(e) => setEffort(e.target.value)}
                  >
                    {selected?.efforts.map((e) => (
                      <option key={e} value={e}>
                        {e}
                      </option>
                    ))}
                  </select>
                </label>
              </>
            )}
            <Button variant="primary" onClick={start} disabled={starting || running || Boolean(state.status.busy)}>
              {(starting || running) && <Spinner />} {running ? "Agent running…" : "Run agent analysis"}
            </Button>
          </div>
        }
      />
      {error && <Notice tone="rose">{error}</Notice>}
      {!trace && !runId && (
        <Card>
          <p className="text-[13px] leading-relaxed text-slate-400">
            No agent run yet. Inject a fault in Mission Control and let the risk build, then run
            the analysis. The simulation clock pauses while the agent works so its snapshot
            stays consistent.
          </p>
        </Card>
      )}
      {trace && (
        <>
          <Card
            title={
              <span className="flex flex-wrap items-center gap-2.5">
                <span className="font-mono text-[13px]">Run {trace.run_id}</span>
                <Badge tone={trace.status === "completed" ? "emerald" : trace.status === "failed" ? "rose" : "cyan"}>{trace.status}</Badge>
                <Badge tone={trace.provider === "deterministic-planner" ? "slate" : "violet"}>
                  {trace.provider}
                  {trace.model ? ` · ${trace.model.split("/").pop()}` : ""}
                </Badge>
                {trace.reasoning_effort && trace.provider !== "deterministic-planner" && (
                  <Badge tone="slate">effort {trace.reasoning_effort}</Badge>
                )}
              </span>
            }
            subtitle={`Snapshot at T+${simClock(trace.snapshot_t_s)} · ${trace.latency_ms ? `${(trace.latency_ms / 1000).toFixed(1)} s` : "in progress"}`}
          >
            <StageBar trace={trace} />
            {trace.notice && <div className="mt-4"><Notice tone="amber">{trace.notice}</Notice></div>}
            {trace.error && <div className="mt-4"><Notice tone="rose">{trace.error}</Notice></div>}
            <div className="mt-4 grid grid-cols-2 gap-px overflow-hidden rounded-[5px] border border-slate-800 bg-slate-800 sm:grid-cols-4 lg:grid-cols-7">
              {[
                ["LLM calls", trace.usage.llm_calls],
                ["Tool calls", trace.usage.tool_calls],
                ["Tool errors", trace.usage.tool_errors],
                ["Invalid actions", trace.usage.invalid_actions],
                ["Unknown evidence ids", trace.usage.hallucinated_evidence_ids],
                ["Tokens in/out", `${trace.usage.input_tokens}/${trace.usage.output_tokens}`],
                ["Est. cost", `$${trace.usage.estimated_cost_usd.toFixed(4)}`],
              ].map(([k, v]) => (
                <div key={String(k)} className="bg-slate-900 px-3 py-2.5">
                  <div className="text-[11px] text-slate-500">{k}</div>
                  <div className="mt-1 font-mono text-[14px] tabular-nums text-slate-100">{v}</div>
                </div>
              ))}
            </div>
          </Card>

          <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_440px]">
            <div className="space-y-6">
              {trace.hypotheses.length > 0 && (
                <Card title="Hypotheses" actions={<ProvenanceTag kind={trace.hypotheses[0].source === "llm" ? "llm_hypothesis" : "heuristic"} />} flush>
                  <ul className="divide-y divide-slate-800">
                    {trace.hypotheses.map((h, i) => (
                      <li key={i} className="grid grid-cols-[2rem_minmax(0,1fr)] gap-x-3 px-5 py-4 text-[13px]">
                        <span className="font-mono text-[11px] text-slate-600">H{i + 1}</span>
                        <div className="min-w-0">
                        <div className="flex items-center gap-2">
                          <Badge tone="violet">{h.failure_mode}</Badge>
                          <Badge tone={h.likelihood === "high" ? "rose" : h.likelihood === "medium" ? "amber" : "slate"}>{h.likelihood}</Badge>
                        </div>
                        <p className="mt-2 leading-relaxed text-slate-200">{h.statement}</p>
                        {h.would_be_refuted_by && <p className="mt-1.5 text-[12px] text-slate-500"><span className="text-slate-400">Refuted by:</span> {h.would_be_refuted_by}</p>}
                        <div className="mt-2 flex flex-wrap gap-1">
                          {h.supporting_evidence_ids.map((id) => (
                            <span key={id} className="rounded-[3px] border border-slate-800 bg-slate-950 px-1.5 py-0.5 font-mono text-[10px] text-slate-400">{id}</span>
                          ))}
                          {h.unknown_evidence_ids.map((id) => (
                            <Badge key={id} tone="rose" title="Cited id does not exist in the evidence registry">unknown: {id}</Badge>
                          ))}
                        </div>
                        </div>
                      </li>
                    ))}
                  </ul>
                </Card>
              )}
              <Card title="Execution trace" subtitle="Every tool call, model call, verification and stage transition" flush>
                <ol className="divide-y divide-slate-800">
                  {trace.steps.map((s) => (
                    <StepRow key={s.seq} step={s} />
                  ))}
                </ol>
              </Card>
            </div>

            <div className="space-y-6">
              {trace.rejected.length > 0 && (
                <Card title={`Rejected by the verifier (${trace.rejected.length})`} subtitle="Proposals blocked before reaching you">
                  <div className="space-y-4">
                    {trace.rejected.map((r, i) => (
                      <div key={i} className="rounded-[5px] border border-slate-800 border-l-2 border-l-rose-400 p-4">
                        <div className="mb-3 flex items-center gap-2 text-[13px]">
                          <span className="font-medium text-slate-100">{r.action_label}</span>
                          <Badge tone="slate">from {r.source}</Badge>
                        </div>
                        <VerificationView v={r.verification} />
                      </div>
                    ))}
                  </div>
                </Card>
              )}
              {rec && (
                <Card
                  title="Recommendation"
                  subtitle={`Selected by ${rec.selected_by.replaceAll("_", " ")} · rationale from ${rec.rationale_source}`}
                  className={rec.status === "awaiting_approval" ? "border-slate-600" : undefined}
                >
                  <div className="space-y-5">
                    <div>
                      <Badge
                        tone={
                          rec.status === "awaiting_approval"
                            ? "cyan"
                            : rec.status === "gather_information"
                              ? "amber"
                              : rec.status === "no_action_needed"
                                ? "emerald"
                                : "rose"
                        }
                      >
                        {rec.status === "gather_information" ? "gathering data · action held back" : rec.status.replaceAll("_", " ")}
                      </Badge>
                      <div className="mt-2.5 text-[22px] font-medium leading-tight tracking-[-0.015em] text-slate-50">{rec.action_label}</div>
                      <p className="mt-2 text-[13px] leading-relaxed text-slate-400">{rec.rationale}</p>
                    </div>
                    {rec.information && <InformationGate info={rec.information} />}
                    {rec.branch && rec.baseline && (
                      <div>
                        <div className="grid grid-cols-[minmax(0,1fr)_auto_auto] gap-x-6 border-y border-slate-800 py-2 font-mono text-[10.5px] uppercase tracking-[0.08em] text-slate-500">
                          <span>Simulated outcome</span>
                          <span className="text-right text-slate-200">This action</span>
                          <span className="text-right">No action</span>
                        </div>
                        {[
                          ["Failure incidence", pct(rec.branch.failure_incidence), pct(rec.baseline.failure_incidence)],
                          ["Objective", usd(rec.branch.objective), usd(rec.baseline.objective)],
                        ].map(([k, a, b]) => (
                          <div key={k} className="grid grid-cols-[minmax(0,1fr)_auto_auto] gap-x-6 border-b border-slate-800 py-2 text-[12px]">
                            <span className="text-slate-400">{k}</span>
                            <span className="text-right font-mono tabular-nums text-slate-50">{a}</span>
                            <span className="text-right font-mono tabular-nums text-slate-500">{b}</span>
                          </div>
                        ))}
                        <div className="mt-2"><ProvenanceTag kind="simulation_estimate" /></div>
                      </div>
                    )}
                    {rec.cited_evidence.length > 0 && (
                      <div>
                        <Eyebrow className="mb-2">Cited evidence</Eyebrow>
                        <EvidenceList items={rec.cited_evidence} />
                      </div>
                    )}
                    {rec.verification && (
                      <div>
                        <Eyebrow className="mb-2">Safety verification</Eyebrow>
                        <VerificationView v={rec.verification} />
                      </div>
                    )}
                    {(rec.status === "awaiting_approval" || rec.status === "gather_information") && rec.action && !applied && (
                      <div className="space-y-3 rounded-[5px] border border-slate-700 bg-slate-950 p-4">
                        <label className="flex items-start gap-2.5 text-[12px] leading-relaxed text-slate-300">
                          <input type="checkbox" checked={approve} onChange={(e) => setApprove(e.target.checked)} className="mt-0.5 accent-slate-100" />
                          {rec.status === "gather_information"
                            ? "The system recommends waiting for more telemetry. I want to apply the held-back action now anyway. "
                            : "I have reviewed the evidence and approve "}
                          &ldquo;{rec.action_label}&rdquo;. It will be re-verified against the current state before execution.
                        </label>
                        <Button variant={rec.status === "gather_information" ? "secondary" : "primary"} className="w-full" onClick={applyRecommendation} disabled={!approve || applying}>
                          {applying && <Spinner />} {rec.status === "gather_information" ? "Override and apply now" : "Approve and apply"}
                        </Button>
                      </div>
                    )}
                    {applied && (
                      <Notice tone="emerald">
                        Applied: {applied}. Watch the outcome in <Link href="/" className="text-slate-50 underline decoration-slate-600 underline-offset-4">Mission Control</Link>.
                      </Notice>
                    )}
                  </div>
                </Card>
              )}
              {trace.summary && (
                <Card title="Summary">
                  <p className="whitespace-pre-wrap text-[13px] leading-relaxed text-slate-300">{trace.summary}</p>
                </Card>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
