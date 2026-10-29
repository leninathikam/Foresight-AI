"use client";

import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { num, usd } from "@/lib/format";
import { PALETTE, ReliabilityChart, SimpleBarChart } from "./charts";
import { Badge, Card, Eyebrow, Notice, PageHeader, Segmented, Spinner, cx } from "./ui";

interface MethodMetrics {
  threshold: number | null;
  threshold_source: string;
  precision: number | null;
  recall: number | null;
  f1: number | null;
  pr_auc: number | null;
  roc_auc: number | null;
  false_positive_rate: number | null;
  brier: number | null;
  ece: number | null;
  is_probability: boolean;
  episode: {
    failing_episodes: number;
    failing_detected: number;
    lead_time_min_median: number | null;
    lead_time_min_p10: number | null;
    lead_time_min_p90: number | null;
    healthy_episodes: number;
    healthy_episodes_with_alarm: number;
    non_failing_episodes: number;
    non_failing_episodes_with_alarm: number;
  };
  reliability?: { mean_predicted: number | null; observed_frequency: number | null; count: number }[];
}

interface PolicySummary {
  episodes: number;
  failures: number;
  failure_rate: number | null;
  failure_rate_ci95: [number, number];
  cost_mean: number | null;
  downtime_h_mean: number;
  interventions_mean: number;
}

interface Detector {
  faulted_episodes: number;
  detected: number;
  missed: number;
  episodes_with_pre_onset_alarm: number;
  detection_delay_min_median: number | null;
  detection_delay_min_p90: number | null;
  healthy_episodes: number;
  healthy_episodes_with_alarm: number;
}

interface AgentMetrics {
  status?: string;
  reason?: string;
  provider?: string;
  model?: string;
  runs?: number;
  completion_rate?: number;
  recommendation_rate?: number;
  tool_success_rate?: number | null;
  invalid_actions?: number;
  verifier_rejections?: number;
  runs_with_rejection?: number;
  latency_ms?: { p50: number | null; p95: number | null };
  estimated_cost_usd?: number;
  hallucinated_evidence_ids?: number;
  fallbacks?: number;
}

interface RateCI {
  k: number;
  n: number;
  rate: number | null;
  ci95: [number, number];
}

interface LiveArm extends AgentMetrics {
  arm: string;
  provider_label: string;
  effort: string;
  mean_regret_vs_planner_usd?: number;
  mean_regret_ci95?: [number, number] | null;
  runs_worse_than_planner?: number;
  runs_better_than_planner?: number;
  unsafe_choice?: RateCI;
  healthy_false_intervention?: RateCI;
}

interface LiveEval extends AgentMetrics {
  arms?: LiveArm[];
  cases?: string[];
  repeats?: number;
  generated_at?: string;
  verifier_label?: string;
}

interface RedTeamAttacker {
  attacker: string;
  model?: string;
  provider_label?: string;
  attempts: number;
  blocked: number;
  accepted: number;
  hard_escapes: number;
  hard_escape_rate: RateCI;
  soft_escapes: number;
  soft_issue_counts: Record<string, number>;
  accepted_ok: number;
  blocking_check_hits: Record<string, number>;
  usage?: { cost_usd: number; calls: number };
}

interface RedTeamReport {
  generated_at: string;
  label: string | null;
  cases: string[];
  rounds: number;
  per_round: number;
  audit: { members: number; seed: number };
  attackers: RedTeamAttacker[];
  random_fuzz: RedTeamAttacker;
}

interface ClosedLoop {
  seeds: number[];
  scenarios: string[];
  episode_hours: number;
  policy_notes: Record<string, string>;
  approval_note: string;
  by_policy: Record<string, { overall: PolicySummary; by_scenario: Record<string, PolicySummary>; healthy_episodes_with_intervention: number }>;
  paired_vs_no_action: Record<string, { mean_cost_change_vs_no_action: number; episodes_cheaper: number; episodes_costlier: number }>;
}

interface CalibrationSummary {
  branches: number;
  brier: number;
  brier_reference_state: number;
  brier_base_rate: number;
  predicted_safe_branches: number;
  false_safe_branches: number;
  false_safe_mean_true_failure_rate: number | null;
  peak_temperature_p10_p90_coverage: number;
  peak_temperature_median_abs_error_k: number;
  decisions: number;
  decision_matches_reference_best: number;
  decision_regret_mean_usd: number;
  decision_regret_max_usd: number;
}

interface Counterfactual {
  seeds: number[];
  decision_minutes: number[];
  actions: string[];
  members: number;
  reference: string;
  decision_points: number;
  modes: Record<
    string,
    {
      overall: CalibrationSummary;
      by_fault_state?: Record<string, Partial<CalibrationSummary>>;
      false_safe_cases: { case: string; action: string; true_failure_rate: number; fault_state?: string }[];
    }
  >;
}

interface Evaluation {
  generated_at: string;
  git_commit: string | null;
  model_version: string;
  runtime_s: number;
  data: Record<string, { episodes: number; rows: number; seeds: [number, number] }>;
  predictive: {
    risk: {
      horizons: Record<string, { positives: number; rows: number; prevalence: number; methods: Record<string, MethodMetrics> }>;
      method_notes: Record<string, string>;
    };
    detection: Record<string, Detector | string>;
    diagnosis: {
      classes: string[];
      all_rows: { rows: number; accuracy: number; macro_f1: number; confusion_matrix: number[][] };
      rows_30min_after_onset_or_healthy: { rows: number; accuracy: number; macro_f1: number; confusion_matrix: number[][] };
      notes: string;
    };
    latency: { per_assessment_ms_p50: number; per_assessment_ms_p95: number; scope: string };
  };
  interventions: ClosedLoop;
  interventions_confirmation?: (ClosedLoop & { note: string }) | null;
  interventions_holdout?: (ClosedLoop & { note: string }) | null;
  counterfactual?: Counterfactual | null;
  agent: { deterministic: AgentMetrics; live: LiveEval; live_recheck?: LiveEval; live_v4?: LiveEval };
  limitations: string[];
}

const METHOD_LABEL: Record<string, string> = {
  xgboost_calibrated: "XGBoost (calibrated)",
  xgboost_raw: "XGBoost (raw)",
  logistic_regression: "Logistic regression",
  zscore_max: "Z-score baseline",
  alarm_threshold_rule: "Alarm threshold rule",
  temperature_extrapolation: "Temperature extrapolation",
};

const POLICY_LABEL: Record<string, string> = {
  no_action: "No action",
  rule_derate: "Rule: derate on alarm",
  rule_shutdown_on_alarm: "Rule: shutdown on alarm",
  rule_inspect_on_alarm: "Rule: inspect on alarm",
  ml_inspect_on_risk: "ML risk → inspect (no simulation)",
  foresight_estimated: "Foresight (estimated state)",
  foresight_active: "Foresight + information gate",
  foresight_oracle: "Foresight (oracle state)",
};

function Th({ children, right }: { children: React.ReactNode; right?: boolean }) {
  return <th className={cx("whitespace-nowrap px-3 pb-2.5 font-mono text-[10.5px] font-medium uppercase tracking-[0.08em] text-slate-500 first:pl-0 last:pr-0", right && "text-right")}>{children}</th>;
}

function Td({ children, right, strong }: { children: React.ReactNode; right?: boolean; strong?: boolean }) {
  return (
    <td className={cx("border-t border-slate-800 px-3 py-2 text-[12px] first:pl-0 last:pr-0", right && "text-right font-mono tabular-nums", strong ? "text-slate-50" : "text-slate-400")}>
      {children}
    </td>
  );
}

export function EvaluationView() {
  const [ev, setEv] = useState<Evaluation | null>(null);
  const [error, setError] = useState<{ message: string; missing: boolean } | null>(null);
  const [horizon, setHorizon] = useState("60");

  useEffect(() => {
    let cancelled = false;
    api
      .evaluation()
      .then((e) => !cancelled && setEv(e as unknown as Evaluation))
      .catch((e: unknown) => {
        if (cancelled) return;
        setError({
          message: e instanceof Error ? e.message : String(e),
          missing: e instanceof ApiError && e.status === 404,
        });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (error) {
    return (
      <Notice tone={error.missing ? "amber" : "rose"}>
        {error.missing ? (
          <>
            No evaluation report has been generated yet. Run{" "}
            <code className="font-mono">uv run python scripts/run_evaluation.py</code>.
          </>
        ) : (
          error.message
        )}
      </Notice>
    );
  }
  if (!ev) {
    return (
      <div className="flex items-center gap-2 py-20 text-sm text-slate-400">
        <Spinner /> Loading evaluation report…
      </div>
    );
  }

  const block = ev.predictive.risk.horizons[horizon];
  const methods = Object.entries(block.methods);
  const iv = ev.interventions;
  const policies = Object.entries(iv.by_policy);
  const detectors = Object.entries(ev.predictive.detection).filter(
    (e): e is [string, Detector] => typeof e[1] === "object",
  );
  const cal = block.methods.xgboost_calibrated?.reliability ?? [];
  const raw = block.methods.xgboost_raw?.reliability ?? [];
  const diag = ev.predictive.diagnosis.rows_30min_after_onset_or_healthy;

  return (
    <div className="space-y-6">
      <PageHeader
        index="04"
        section="Evidence"
        title="Evaluation report"
        description={
          <>
            Every number on this page is loaded from <code className="font-mono text-[13px] text-slate-300">artifacts/reports/evaluation.json</code>, generated by{" "}
            <code className="font-mono text-[13px] text-slate-300">scripts/run_evaluation.py</code> on held-out simulator seeds. Nothing is
            hand-entered, and negative results are kept in.
          </>
        }
        meta={
          <>
            <Badge>Generated {new Date(ev.generated_at).toLocaleString()}</Badge>
            <Badge>git {ev.git_commit ?? "unknown"}</Badge>
            <Badge>{ev.model_version}</Badge>
            <Badge>{num(ev.runtime_s, 0)} s runtime</Badge>
          </>
        }
      />

      <div className="grid gap-px overflow-hidden rounded-md border border-slate-800 bg-slate-800 sm:grid-cols-3">
        {Object.entries(ev.data).map(([split, d]) => (
          <div key={split} className="bg-slate-900 px-5 py-4">
            <Eyebrow>{split} split</Eyebrow>
            <div className="mt-3 font-mono text-[24px] leading-none tabular-nums text-slate-50">
              {d.episodes}
              <span className="ml-1.5 text-[13px] text-slate-500">episodes</span>
            </div>
            <div className="mt-2.5 font-mono text-[11px] text-slate-500">
              {d.rows.toLocaleString()} rows · seeds {d.seeds[0]}–{d.seeds[1]}
            </div>
          </div>
        ))}
      </div>

      <Card
        title="Failure-risk prediction vs baselines"
        subtitle={`Test split · ${block.positives} positive of ${block.rows.toLocaleString()} rows (prevalence ${num(block.prevalence * 100, 1)}%)`}
        actions={
          <Segmented options={Object.keys(ev.predictive.risk.horizons)} value={horizon} onChange={setHorizon} format={(h) => `≤ ${h} min`} />
        }
      >
        <div className="overflow-x-auto">
          <table className="w-full min-w-[900px] text-left">
            <thead>
              <tr>
                <Th>Method</Th>
                <Th right>Precision</Th>
                <Th right>Recall</Th>
                <Th right>F1</Th>
                <Th right>PR-AUC</Th>
                <Th right>FPR</Th>
                <Th right>Brier</Th>
                <Th right>ECE</Th>
                <Th right>Failures alarmed</Th>
                <Th right>Median lead</Th>
                <Th right>Healthy eps alarmed</Th>
              </tr>
            </thead>
            <tbody>
              {methods.map(([name, m]) => (
                <tr key={name}>
                  <Td strong={name === "xgboost_calibrated"}>
                    <span title={ev.predictive.risk.method_notes[name]}>{METHOD_LABEL[name] ?? name}</span>
                    <span className="block text-[10px] text-slate-500">threshold: {m.threshold_source}</span>
                  </Td>
                  <Td right>{num(m.precision, 3)}</Td>
                  <Td right>{num(m.recall, 3)}</Td>
                  <Td right>{num(m.f1, 3)}</Td>
                  <Td right>{num(m.pr_auc, 3)}</Td>
                  <Td right>{num(m.false_positive_rate, 3)}</Td>
                  <Td right>{num(m.brier, 3)}</Td>
                  <Td right>{num(m.ece, 3)}</Td>
                  <Td right>
                    {m.episode.failing_detected}/{m.episode.failing_episodes}
                  </Td>
                  <Td right>{m.episode.lead_time_min_median === null ? "—" : `${num(m.episode.lead_time_min_median, 0)} min`}</Td>
                  <Td right>
                    {m.episode.healthy_episodes_with_alarm}/{m.episode.healthy_episodes}
                  </Td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="mt-5 grid gap-5 lg:grid-cols-2">
          <div>
            <div className="mb-1 text-xs text-slate-400">PR-AUC by method (higher is better)</div>
            <SimpleBarChart
              data={methods.map(([n, m]) => ({ name: (METHOD_LABEL[n] ?? n).replace(" (", "\n("), pr_auc: m.pr_auc }))}
              bars={[{ key: "pr_auc", name: "PR-AUC", color: PALETTE.model }]}
              yFormatter={(v) => v.toFixed(2)}
            />
          </div>
          <div>
            <div className="mb-1 text-xs text-slate-400">Reliability diagram (test split)</div>
            <ReliabilityChart
              series={[
                { name: "calibrated", color: PALETTE.accent, points: cal },
                { name: "raw", color: PALETTE.thermal, points: raw },
              ]}
            />
          </div>
        </div>
      </Card>

      <div className="grid gap-5 lg:grid-cols-2">
        <Card title="Anomaly and change-point detection" subtitle="Detection delay after scripted fault onset (includes the latent period)">
          <table className="w-full text-left">
            <thead>
              <tr>
                <Th>Detector</Th>
                <Th right>Detected</Th>
                <Th right>Median delay</Th>
                <Th right>p90 delay</Th>
                <Th right>Pre-onset alarms</Th>
                <Th right>Healthy alarmed</Th>
              </tr>
            </thead>
            <tbody>
              {detectors.map(([n, d]) => (
                <tr key={n}>
                  <Td strong>{n === "cusum_any" ? "CUSUM (any signal)" : "Isolation forest"}</Td>
                  <Td right>{d.detected}/{d.faulted_episodes}</Td>
                  <Td right>{num(d.detection_delay_min_median, 1)} min</Td>
                  <Td right>{num(d.detection_delay_min_p90, 1)} min</Td>
                  <Td right>{d.episodes_with_pre_onset_alarm}</Td>
                  <Td right>{d.healthy_episodes_with_alarm}/{d.healthy_episodes}</Td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-3 text-xs text-slate-500">
            Inference latency p50 {num(ev.predictive.latency.per_assessment_ms_p50, 1)} ms, p95{" "}
            {num(ev.predictive.latency.per_assessment_ms_p95, 1)} ms ({ev.predictive.latency.scope}).
          </p>
        </Card>
        <Card title="Fault diagnosis" subtitle={`Rows ≥ 30 min after onset, plus healthy rows: accuracy ${num(diag.accuracy * 100, 1)}%, macro F1 ${num(diag.macro_f1, 3)}`}>
          <table className="w-full text-center text-xs">
            <thead>
              <tr>
                <th className="pb-2 text-left text-[11px] font-medium text-slate-500">true ↓ / predicted →</th>
                {ev.predictive.diagnosis.classes.map((c) => (
                  <th key={c} className="pb-2 text-[11px] font-medium text-slate-500">{c}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {diag.confusion_matrix.map((row, i) => {
                const total = row.reduce((a, b) => a + b, 0) || 1;
                return (
                  <tr key={i}>
                    <td className="py-1 text-left text-slate-400">{ev.predictive.diagnosis.classes[i]}</td>
                    {row.map((v, j) => (
                      <td key={j} className="py-1 font-mono tabular-nums" style={{ background: `rgba(112,150,250,${(v / total) * 0.4})` }}>
                        {v}
                      </td>
                    ))}
                  </tr>
                );
              })}
            </tbody>
          </table>
          <p className="mt-2 text-[11px] text-slate-500">
            All rows: accuracy {num(ev.predictive.diagnosis.all_rows.accuracy * 100, 1)}%. {ev.predictive.diagnosis.notes}
          </p>
        </Card>
      </div>

      <Card
        title="Closed-loop intervention outcomes"
        subtitle={`${iv.scenarios.length} scenarios × ${iv.seeds.length} held-out seeds (${iv.seeds[0]}–${iv.seeds[iv.seeds.length - 1]}) × ${iv.episode_hours} h per episode. ${iv.approval_note}`}
      >
        <PolicyTable iv={iv} />
        <div className="mt-5">
          <div className="mb-1 text-xs text-slate-400">Mean episode cost by scenario (USD, lower is better)</div>
          <SimpleBarChart
            height={280}
            data={iv.scenarios.map((sc) => ({
              name: sc.replaceAll("_", " "),
              ...Object.fromEntries(policies.map(([p, b]) => [p, b.by_scenario[sc]?.cost_mean ?? null])),
            }))}
            bars={policies.map(([p], i) => ({
              key: p,
              name: POLICY_LABEL[p] ?? p,
              color: ["#3f3f3c", "#52524f", "#8f8f8a", "#d3d3cf", "#b08968", PALETTE.thermal, PALETTE.accent, PALETTE.model][i % 8],
            }))}
            yFormatter={(v) => `$${Math.round(v / 100) / 10}k`}
          />
        </div>
        <ul className="mt-3 space-y-0.5 text-[11px] text-slate-500">
          {Object.entries(iv.policy_notes).map(([p, n]) => (
            <li key={p}>
              <span className="text-slate-400">{POLICY_LABEL[p] ?? p}:</span> {n}
            </li>
          ))}
        </ul>
      </Card>

      {ev.interventions_confirmation && (
        <SeedBlockCard title="Confirmation on further test seeds" iv={ev.interventions_confirmation} />
      )}
      {ev.interventions_holdout && <SeedBlockCard title="Final hold-out seeds" iv={ev.interventions_holdout} />}

      {ev.counterfactual && <CounterfactualCard cf={ev.counterfactual} />}

      <div className="grid gap-5 lg:grid-cols-2">
        <Card title="Agent reliability" subtitle={ev.agent.deterministic.provider ? `Provider: ${ev.agent.deterministic.provider}` : undefined}>
          {ev.agent.deterministic.runs ? (
            <dl className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-xs">
              {[
                ["Runs", ev.agent.deterministic.runs],
                ["Completion rate", num((ev.agent.deterministic.completion_rate ?? 0) * 100, 1) + "%"],
                ["Runs that recommended an action", num((ev.agent.deterministic.recommendation_rate ?? 0) * 100, 1) + "%"],
                ["Tool success rate", ev.agent.deterministic.tool_success_rate === null || ev.agent.deterministic.tool_success_rate === undefined ? "—" : num(ev.agent.deterministic.tool_success_rate * 100, 1) + "%"],
                ["Invalid actions", ev.agent.deterministic.invalid_actions],
                ["Verifier rejections", ev.agent.deterministic.verifier_rejections],
                ["Latency p50 / p95", `${num((ev.agent.deterministic.latency_ms?.p50 ?? 0) / 1000, 1)} / ${num((ev.agent.deterministic.latency_ms?.p95 ?? 0) / 1000, 1)} s`],
                ["Model cost", `$${(ev.agent.deterministic.estimated_cost_usd ?? 0).toFixed(4)}`],
              ].map(([k, v]) => (
                <div key={String(k)} className="contents">
                  <dt className="text-slate-500">{k}</dt>
                  <dd className="text-right font-mono tabular-nums text-slate-200">{v}</dd>
                </div>
              ))}
            </dl>
          ) : (
            <p className="text-sm text-slate-500">No deterministic runs recorded.</p>
          )}
          <div className="mt-4">
            {ev.agent.live.status === "run" && ev.agent.live.arms ? (
              <Notice tone="cyan">
                Live model comparison: {ev.agent.live.arms.length} provider/effort arms,{" "}
                {ev.agent.live.runs} runs, total cost ${(ev.agent.live.estimated_cost_usd ?? 0).toFixed(2)}. See
                the table below.
              </Notice>
            ) : ev.agent.live.status === "run" ? (
              <Notice tone="cyan">
                Live Meta model ({ev.agent.live.model}): {ev.agent.live.runs} runs, completion{" "}
                {num((ev.agent.live.completion_rate ?? 0) * 100, 0)}%, verifier rejections{" "}
                {ev.agent.live.verifier_rejections}, unknown evidence ids {ev.agent.live.hallucinated_evidence_ids}, fallbacks{" "}
                {ev.agent.live.fallbacks}, cost ${(ev.agent.live.estimated_cost_usd ?? 0).toFixed(4)}.
              </Notice>
            ) : (
              <Notice tone="amber">Live model evaluation not run: {ev.agent.live.reason}</Notice>
            )}
          </div>
        </Card>
        <Card title="Limitations">
          <ul className="list-disc space-y-1.5 pl-4 text-xs text-slate-400">
            {ev.limitations.map((l) => (
              <li key={l}>{l}</li>
            ))}
          </ul>
        </Card>
      </div>
      {ev.agent.live.arms && <LiveArmsCard title="Live model comparison" live={ev.agent.live} />}
      {ev.agent.live_recheck?.arms && (
        <LiveArmsCard title="Re-check after verifier fixes" live={ev.agent.live_recheck} />
      )}
      {ev.agent.live_v4?.arms && (
        <LiveArmsCard title="Re-check on verifier v4 with the information gate" live={ev.agent.live_v4} />
      )}
      <RedTeamCard />
    </div>
  );
}

function PolicyTable({ iv }: { iv: ClosedLoop }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[820px] text-left">
        <thead>
          <tr>
            <Th>Policy</Th>
            <Th right>Failures</Th>
            <Th right>95% CI</Th>
            <Th right>Mean cost</Th>
            <Th right>Δ vs no action</Th>
            <Th right>Downtime</Th>
            <Th right>Interventions</Th>
            <Th right>Healthy eps touched</Th>
          </tr>
        </thead>
        <tbody>
          {Object.entries(iv.by_policy).map(([p, b]) => (
            <tr key={p}>
              <Td strong={p.startsWith("foresight")}>
                <span title={iv.policy_notes[p]}>{POLICY_LABEL[p] ?? p}</span>
              </Td>
              <Td right>{b.overall.failures}/{b.overall.episodes}</Td>
              <Td right>{num(b.overall.failure_rate_ci95[0], 2)}–{num(b.overall.failure_rate_ci95[1], 2)}</Td>
              <Td right>{usd(b.overall.cost_mean)}</Td>
              <Td right>{iv.paired_vs_no_action[p] ? usd(iv.paired_vs_no_action[p].mean_cost_change_vs_no_action) : "—"}</Td>
              <Td right>{num(b.overall.downtime_h_mean, 2)} h</Td>
              <Td right>{num(b.overall.interventions_mean, 2)}</Td>
              <Td right>{b.healthy_episodes_with_intervention}</Td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function SeedBlockCard({ title, iv }: { title: string; iv: ClosedLoop & { note: string } }) {
  return (
    <Card
      title={title}
      subtitle={`${iv.seeds.length} seeds (${iv.seeds[0]}–${iv.seeds[iv.seeds.length - 1]}) × ${iv.scenarios.length} scenarios`}
    >
      <p className="mb-3 text-[12px] leading-relaxed text-slate-400">{iv.note}</p>
      <PolicyTable iv={iv} />
    </Card>
  );
}

const FAULT_STATE_LABEL: Record<string, string> = {
  no_fault: "No fault",
  latent: "Latent (not started yet)",
  active: "Active fault",
};

function CounterfactualCard({ cf }: { cf: Counterfactual }) {
  const modes = Object.entries(cf.modes);
  const byState = Object.entries(cf.modes.fixed?.by_fault_state ?? {}).filter(([, v]) => v.decisions);
  return (
    <Card
      title="Counterfactual calibration"
      subtitle={`${cf.decision_points} held-out decision points · estimated-state ensemble (${cf.members} members) vs the hidden true process`}
    >
      <div className="overflow-x-auto">
        <table className="w-full min-w-[900px] text-left">
          <thead>
            <tr>
              <Th>Trend uncertainty</Th>
              <Th right>Branches</Th>
              <Th right>Brier</Th>
              <Th right>Brier (true state)</Th>
              <Th right>Predicted safe → fails</Th>
              <Th right>Peak-T 10–90 % coverage</Th>
              <Th right>Peak-T |error|</Th>
              <Th right>Best action matched</Th>
              <Th right>Decision regret mean / max</Th>
            </tr>
          </thead>
          <tbody>
            {modes.map(([mode, m]) => (
              <tr key={mode}>
                <Td strong>{mode === "fixed" ? "Fixed spread (planner)" : "Fit standard error"}</Td>
                <Td right>{m.overall.branches}</Td>
                <Td right>{num(m.overall.brier, 3)}</Td>
                <Td right>{num(m.overall.brier_reference_state, 3)}</Td>
                <Td right>
                  {m.overall.false_safe_branches}/{m.overall.predicted_safe_branches}
                </Td>
                <Td right>{num(m.overall.peak_temperature_p10_p90_coverage * 100, 0)}%</Td>
                <Td right>{num(m.overall.peak_temperature_median_abs_error_k, 1)} K</Td>
                <Td right>
                  {m.overall.decision_matches_reference_best}/{m.overall.decisions}
                </Td>
                <Td right>
                  {usd(m.overall.decision_regret_mean_usd)} / {usd(m.overall.decision_regret_max_usd)}
                </Td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {byState.length > 0 && (
        <div className="mt-5 overflow-x-auto">
          <div className="mb-1 text-xs text-slate-400">
            By fault state at the decision point (fixed spread). A latent fault is scheduled but has not started, so no
            telemetry can reveal it; active faults are the fair test of the estimator.
          </div>
          <table className="w-full min-w-[760px] text-left">
            <thead>
              <tr>
                <Th>Fault state</Th>
                <Th right>Decision points</Th>
                <Th right>Brier</Th>
                <Th right>Predicted safe → fails</Th>
                <Th right>Peak-T 10–90 % coverage</Th>
                <Th right>Best action matched</Th>
                <Th right>Mean regret</Th>
              </tr>
            </thead>
            <tbody>
              {byState.map(([state, v]) => (
                <tr key={state}>
                  <Td strong={state === "active"}>{FAULT_STATE_LABEL[state] ?? state}</Td>
                  <Td right>{v.decisions}</Td>
                  <Td right>{num(v.brier, 3)}</Td>
                  <Td right>
                    {v.false_safe_branches}/{v.predicted_safe_branches}
                  </Td>
                  <Td right>{num((v.peak_temperature_p10_p90_coverage ?? 0) * 100, 0)}%</Td>
                  <Td right>
                    {v.decision_matches_reference_best}/{v.decisions}
                  </Td>
                  <Td right>{usd(v.decision_regret_mean_usd ?? 0)}</Td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="mt-3 text-[11px] leading-relaxed text-slate-500">
        Actions: {cf.actions.join(", ")}. Reference: {cf.reference} &ldquo;Predicted safe → fails&rdquo; counts branches
        where the estimated ensemble shows no failure but the true process sometimes fails; peak-temperature coverage is
        nominally 80 %. Both sides use the same twin equations, so this measures state-estimation error, not model-form
        error.
      </p>
    </Card>
  );
}

const fmtRate = (r?: RateCI) => (r ? `${r.k}/${r.n}` : "—");
const fmtCi = (r?: RateCI) => (r ? `${r.ci95[0].toFixed(2)}–${r.ci95[1].toFixed(2)}` : "");

function LiveArmsCard({ title, live }: { title: string; live: LiveEval }) {
  const arms = live.arms ?? [];
  return (
    <Card
      title={title}
      subtitle={`${arms.length} arms × ${live.cases?.length ?? 0} cases × ${live.repeats ?? 0} repeats · real API calls${live.verifier_label ? ` · verifier ${live.verifier_label}` : ""}${live.generated_at ? ` · ${live.generated_at}` : ""}`}
    >
      <div className="overflow-x-auto">
        <table className="w-full min-w-[960px] text-left">
          <thead>
            <tr>
              <Th>Provider · effort</Th>
              <Th right>Runs</Th>
              <Th right>Completed</Th>
              <Th right>Mean regret (95% CI)</Th>
              <Th right>Worse / better</Th>
              <Th right>Unsafe pick</Th>
              <Th right>Healthy false alarm</Th>
              <Th right>Rejections</Th>
              <Th right>Fallbacks</Th>
              <Th right>p50 latency</Th>
              <Th right>Cost / run</Th>
            </tr>
          </thead>
          <tbody>
            {arms.map((a) => (
              <tr key={a.arm}>
                <Td strong>
                  {a.provider_label} <span className="font-mono text-slate-500">· {a.effort}</span>
                </Td>
                <Td right>{a.runs}</Td>
                <Td right>{num((a.completion_rate ?? 0) * 100, 0)}%</Td>
                <Td right>
                  {a.mean_regret_vs_planner_usd === undefined ? "—" : usd(a.mean_regret_vs_planner_usd)}
                  {a.mean_regret_ci95 && (
                    <span className="text-slate-500"> [{usd(a.mean_regret_ci95[0])}, {usd(a.mean_regret_ci95[1])}]</span>
                  )}
                </Td>
                <Td right>
                  {a.runs_worse_than_planner ?? "—"} / {a.runs_better_than_planner ?? "—"}
                </Td>
                <Td right>
                  {fmtRate(a.unsafe_choice)} <span className="text-slate-500">{fmtCi(a.unsafe_choice)}</span>
                </Td>
                <Td right>
                  {fmtRate(a.healthy_false_intervention)}{" "}
                  <span className="text-slate-500">{fmtCi(a.healthy_false_intervention)}</span>
                </Td>
                <Td right>{a.verifier_rejections}</Td>
                <Td right>{a.fallbacks}</Td>
                <Td right>{num((a.latency_ms?.p50 ?? 0) / 1000, 1)} s</Td>
                <Td right>${((a.estimated_cost_usd ?? 0) / Math.max(1, a.runs ?? 1)).toFixed(4)}</Td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-3 text-[11px] leading-relaxed text-slate-500">
        Regret is the agent&apos;s chosen action minus the deterministic planner&apos;s, scored in one shared
        audit ensemble (positive = agent worse under the simulator&apos;s cost model). Regret CIs are
        bootstrap; rate CIs are Wilson 95%. Unsafe pick = the recommended action still fails in the audit.
      </p>
    </Card>
  );
}

function RedTeamCard() {
  const [data, setData] = useState<{ current: RedTeamReport; history: RedTeamReport[] } | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .redteam()
      .then((d) => !cancelled && setData(d as unknown as { current: RedTeamReport; history: RedTeamReport[] }))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  if (!data) return null;
  const reports = [...data.history, data.current];
  return (
    <Card
      title="Verifier red-team"
      subtitle={`Adversarial models try to get bad interventions past the verifier · ${data.current.cases.length} cases × ${data.current.rounds} adaptive rounds × ${data.current.per_round} proposals per attacker`}
    >
      <div className="overflow-x-auto">
        <table className="w-full min-w-[860px] text-left">
          <thead>
            <tr>
              <Th>Verifier</Th>
              <Th>Attacker</Th>
              <Th right>Attempts</Th>
              <Th right>Blocked</Th>
              <Th right>Hard escapes (95% CI)</Th>
              <Th right>Soft escapes</Th>
              <Th right>Accepted &amp; fine</Th>
              <Th right>Attacker cost</Th>
            </tr>
          </thead>
          <tbody>
            {reports.flatMap((r) =>
              [...r.attackers, r.random_fuzz].map((a) => (
                <tr key={`${r.generated_at}-${a.attacker}`}>
                  <Td>{r.label ?? r.generated_at}</Td>
                  <Td strong>{a.attacker === "random_fuzz" ? "Random fuzz (control)" : `${a.provider_label} · ${a.attacker.split(":")[1]}`}</Td>
                  <Td right>{a.attempts}</Td>
                  <Td right>{a.blocked}</Td>
                  <Td right>
                    {a.hard_escapes} <span className="text-slate-500">{fmtCi(a.hard_escape_rate)}</span>
                  </Td>
                  <Td right>{a.soft_escapes}</Td>
                  <Td right>{a.accepted_ok}</Td>
                  <Td right>{a.usage ? `$${a.usage.cost_usd.toFixed(2)}` : "—"}</Td>
                </tr>
              )),
            )}
          </tbody>
        </table>
      </div>
      <p className="mt-3 text-[11px] leading-relaxed text-slate-500">
        Hard escape: accepted, but a fresh {data.current.audit.members}-member audit ensemble shows simulated
        failure or a limit exceedance. Soft escape: accepted although no better than doing nothing,
        unnecessary on a healthy machine, or claiming the wrong failure mode. Full detail in
        artifacts/reports/redteam.md.
      </p>
    </Card>
  );
}
