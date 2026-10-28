"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { DIAGNOSIS_LABEL, num, pct, simClock } from "@/lib/format";
import { useSession } from "@/lib/session-context";
import type { CompactSample, RiskAssessment, ScenarioId, ScenarioInfo } from "@/lib/types";
import { RiskChart, TelemetryChart } from "./charts";
import {
  Badge,
  Button,
  Card,
  Eyebrow,
  Notice,
  PageHeader,
  ProvenanceTag,
  Segmented,
  Spinner,
  Stat,
  StatusDot,
  cx,
  inputClass,
} from "./ui";

const SPEEDS = [10, 30, 60, 120, 300];
const WINDOWS = [30, 60, 120, 240] as const;

const LOOP = [
  ["Observe", "Stream simulated sensor telemetry"],
  ["Predict", "Calibrated failure risk at 15, 30 and 60 min"],
  ["Diagnose", "Classify the most likely fault"],
  ["Simulate", "Branch the twin into alternative futures"],
  ["Verify", "Independent deterministic safety checks"],
  ["Recommend", "Propose an action for your approval"],
] as const;

const SPECS = [
  ["Asset", "15 kW conveyor drive"],
  ["Sampling", "10 s"],
  ["Thermal limit", "155 °C · class F"],
  ["Vibration trip", "7.1 mm/s · ISO 10816"],
] as const;

function latestValue(samples: CompactSample[], key: "T" | "vib" | "load" | "I"): number | null {
  for (let i = samples.length - 1; i >= 0 && i > samples.length - 30; i--) {
    const v = samples[i][key];
    if (v !== null) return v;
  }
  return null;
}

function StartSession() {
  const { startSession, state } = useSession();
  const [scenarios, setScenarios] = useState<ScenarioInfo[] | null>(null);
  const [scenario, setScenario] = useState<ScenarioId>("cooling_degradation");
  const [seed, setSeed] = useState(7);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .scenarios()
      .then((s) => !cancelled && setScenarios(s))
      .catch((e: Error) => !cancelled && setError(e.message));
    return () => {
      cancelled = true;
    };
  }, []);

  const start = async () => {
    setBusy(true);
    setError(null);
    try {
      await startSession(scenario, seed);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="grid gap-14 py-4 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)] lg:gap-20 lg:py-10">
      <div>
        <Eyebrow>Predictive maintenance · Digital twin</Eyebrow>
        <h1 className="mt-5 text-[44px] font-medium leading-[1.04] tracking-[-0.035em] text-slate-50 sm:text-[52px]">
          See the failure
          <br />
          <span className="text-slate-500">before it happens.</span>
        </h1>
        <p className="mt-6 max-w-xl text-[15px] leading-relaxed text-slate-400">
          Foresight runs a live digital twin of an industrial motor drive. When a fault develops, it
          predicts the risk, diagnoses the cause, simulates what each intervention would do, and only
          recommends an action that passes an independent safety verifier, with your approval.
        </p>

        <ol className="mt-10 grid max-w-xl grid-cols-1 border-t border-slate-800 sm:grid-cols-2">
          {LOOP.map(([name, desc], i) => (
            <li
              key={name}
              className={cx(
                "flex gap-4 border-b border-slate-800 py-3.5",
                i % 2 === 0 && "sm:border-r sm:pr-5",
                i % 2 === 1 && "sm:pl-5",
              )}
            >
              <span className="font-mono text-[11px] text-slate-600">{String(i + 1).padStart(2, "0")}</span>
              <span>
                <span className="block text-[13px] font-medium text-slate-100">{name}</span>
                <span className="block text-[12px] text-slate-500">{desc}</span>
              </span>
            </li>
          ))}
        </ol>

        <div className="mt-10 grid max-w-xl grid-cols-2 gap-y-5 sm:grid-cols-4">
          {SPECS.map(([k, v]) => (
            <div key={k}>
              <Eyebrow>{k}</Eyebrow>
              <div className="mt-1.5 font-mono text-[12px] text-slate-300">{v}</div>
            </div>
          ))}
        </div>
      </div>

      <div className="self-start rounded-md border border-slate-800 bg-slate-900">
        <div className="flex items-center justify-between border-b border-slate-800 px-6 py-4">
          <span className="text-[13.5px] font-medium text-slate-100">New simulation session</span>
          <span className="font-mono text-[11px] text-slate-500">simulation only</span>
        </div>
        <div className="space-y-7 px-6 py-6">
          {state.error && <Notice tone="amber">{state.error}</Notice>}
          {error && <Notice tone="rose">{error}</Notice>}
          <div>
            <Eyebrow>
              <span className="text-slate-400">01</span>
              <span className="mx-2 text-slate-700">/</span>Scenario
            </Eyebrow>
            <div className="mt-3 divide-y divide-slate-800 rounded-[5px] border border-slate-800">
              {(scenarios ?? []).map((s) => {
                const active = scenario === s.id;
                return (
                  <button
                    key={s.id}
                    onClick={() => setScenario(s.id)}
                    className={cx(
                      "flex w-full gap-3.5 px-4 py-3.5 text-left transition-colors",
                      active ? "bg-slate-800/70" : "hover:bg-slate-800/35",
                    )}
                  >
                    <span
                      className={cx(
                        "mt-[3px] grid h-3.5 w-3.5 shrink-0 place-items-center rounded-full border",
                        active ? "border-cyan-400" : "border-slate-600",
                      )}
                    >
                      {active && <span className="h-1.5 w-1.5 rounded-full bg-cyan-400" />}
                    </span>
                    <span className="min-w-0">
                      <span className={cx("block text-[13px] font-medium", active ? "text-slate-50" : "text-slate-200")}>
                        {s.title}
                      </span>
                      <span className="mt-0.5 block text-[12px] leading-relaxed text-slate-500">
                        {s.description}
                      </span>
                    </span>
                  </button>
                );
              })}
              {!scenarios && !error && (
                <div className="flex items-center gap-2 px-4 py-4 text-[13px] text-slate-500">
                  <Spinner /> Loading scenarios…
                </div>
              )}
            </div>
          </div>
          <div>
            <Eyebrow>
              <span className="text-slate-400">02</span>
              <span className="mx-2 text-slate-700">/</span>Disturbance seed
            </Eyebrow>
            <div className="mt-3 flex items-center gap-4">
              <input
                type="number"
                min={0}
                value={seed}
                onChange={(e) => setSeed(Number(e.target.value))}
                className={cx(inputClass, "w-24 font-mono")}
                aria-label="Disturbance seed"
              />
              <p className="text-[12px] leading-snug text-slate-500">
                Same seed, same disturbances. Runs are fully reproducible.
              </p>
            </div>
          </div>
          <Button variant="primary" onClick={start} disabled={busy || !scenarios} className="h-10 w-full">
            {busy && <Spinner />} Start live session
          </Button>
        </div>
      </div>
    </div>
  );
}

function Section({ title, right, children }: { title: string; right?: React.ReactNode; children: React.ReactNode }) {
  return (
    <div>
      <div className="mb-2.5 flex items-center justify-between">
        <Eyebrow>{title}</Eyebrow>
        {right}
      </div>
      {children}
    </div>
  );
}

function AssessmentPanel({ a }: { a: RiskAssessment | null }) {
  if (!a) return <p className="text-[13px] text-slate-500">Waiting for the first assessment…</p>;
  if (!a.available)
    return <Notice tone="slate">Assessment unavailable: {a.reason ?? "unknown reason"}</Notice>;
  const observed = a.evidence.filter((e) => e.kind === "observed").slice(0, 5);
  return (
    <div className="space-y-6">
      <Section title="Failure risk" right={<ProvenanceTag kind="ml_prediction" />}>
        <div className="grid grid-cols-3 divide-x divide-slate-800 rounded-[5px] border border-slate-800">
          {a.horizons.map((h) => (
            <div key={h.horizon_min} className="px-3 py-2.5">
              <div className="font-mono text-[10.5px] text-slate-500">≤ {h.horizon_min} min</div>
              <div
                className={cx(
                  "mt-1 font-mono text-[18px] tabular-nums",
                  h.probability >= 0.5
                    ? "text-rose-300"
                    : h.probability >= 0.2
                      ? "text-amber-300"
                      : "text-slate-100",
                )}
              >
                {pct(h.probability, 1)}
              </div>
              <div className="font-mono text-[10px] text-slate-600">raw {pct(h.raw_probability, 1)}</div>
            </div>
          ))}
        </div>
      </Section>
      <Section title="Diagnosis" right={<ProvenanceTag kind="ml_prediction" />}>
        <div className="space-y-2">
          {a.diagnosis.map((d, i) => (
            <div key={d.label} className="grid grid-cols-[minmax(0,9rem)_1fr_3rem] items-center gap-3">
              <span className={cx("truncate text-[12px]", i === 0 ? "text-slate-100" : "text-slate-400")}>
                {DIAGNOSIS_LABEL[d.label] ?? d.label}
              </span>
              <div className="h-[3px] bg-slate-800">
                <div
                  className={cx("h-[3px]", i === 0 ? "bg-slate-100" : "bg-slate-600")}
                  style={{ width: `${Math.max(1, d.probability * 100)}%` }}
                />
              </div>
              <span className="text-right font-mono text-[11px] tabular-nums text-slate-400">
                {pct(d.probability)}
              </span>
            </div>
          ))}
        </div>
      </Section>
      <div className="grid grid-cols-2 gap-px overflow-hidden rounded-[5px] border border-slate-800 bg-slate-800">
        <div className="bg-slate-900 px-3 py-2.5">
          <div className="font-mono text-[10.5px] text-slate-500">Isolation forest</div>
          <div className="mt-1 flex items-center gap-2 font-mono text-[13px] tabular-nums text-slate-200">
            <StatusDot tone={a.anomaly?.is_anomalous ? "rose" : "emerald"} />
            {num(a.anomaly?.score, 3)}
            <span className="text-slate-600">/ {num(a.anomaly?.threshold, 3)}</span>
          </div>
          <div className="mt-0.5 text-[11px] text-slate-500">
            {a.anomaly?.is_anomalous ? "Anomalous" : "Normal"}
          </div>
        </div>
        <div className="bg-slate-900 px-3 py-2.5">
          <div className="font-mono text-[10.5px] text-slate-500">CUSUM change points</div>
          <div className="mt-1.5 flex flex-wrap gap-1">
            {a.change_points.map((c) => (
              <Badge key={c.signal} tone={c.detected ? "amber" : "slate"} title={`statistic ${c.statistic.toFixed(1)}`}>
                {c.signal}
                {c.detected && c.t_s !== null ? ` @${Math.round(c.t_s / 60)}m` : ""}
              </Badge>
            ))}
          </div>
        </div>
      </div>
      <Section title="Largest deviations vs healthy" right={<ProvenanceTag kind="observed" />}>
        <table className="w-full text-[12px]">
          <tbody className="divide-y divide-slate-800">
            {observed.map((e) => (
              <tr key={e.id}>
                <td className="py-1.5 text-slate-300" title={e.description}>
                  {e.signal}
                </td>
                <td className="py-1.5 text-right font-mono tabular-nums text-slate-200">
                  {num(e.value, 2)} <span className="text-slate-500">{e.unit}</span>
                </td>
                <td className="w-16 py-1.5 text-right font-mono tabular-nums text-slate-500">
                  z {num(e.z_score, 1)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Section>
      {a.heuristic_minutes_to_temp_limit !== null && (
        <div className="flex items-center justify-between gap-3 text-[12px] text-slate-400">
          <span>
            Linear trend reaches 155 °C in ~{num(a.heuristic_minutes_to_temp_limit, 0)} min
          </span>
          <ProvenanceTag kind="heuristic" />
        </div>
      )}
      <p className="border-t border-slate-800 pt-3 font-mono text-[10.5px] text-slate-600">
        {a.model_version} · {num(a.latency_ms, 1)} ms · T+{simClock(a.t_s)}
      </p>
    </div>
  );
}

function ChartLabel({ children }: { children: React.ReactNode }) {
  return <div className="mb-2 text-[12px] text-slate-400">{children}</div>;
}

export function MissionControl() {
  const { state, endSession } = useSession();
  const router = useRouter();
  const [windowMin, setWindowMin] = useState<(typeof WINDOWS)[number]>(120);
  const [showTruth, setShowTruth] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<string | null>(null);

  if (!state.sessionId) return <StartSession />;
  const s = state.status;
  if (!s) {
    return (
      <div className="flex items-center gap-2 py-20 text-[13px] text-slate-500">
        <Spinner /> Connecting to session…
      </div>
    );
  }

  const run = async (label: string, fn: () => Promise<unknown>) => {
    setPending(label);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setPending(null);
    }
  };

  const T = latestValue(state.samples, "T");
  const vib = latestValue(state.samples, "vib");
  const load = latestValue(state.samples, "load");
  const risk60 = state.assessment?.available
    ? state.assessment.horizons.find((h) => h.horizon_min === 60)?.probability ?? null
    : null;
  const top = state.assessment?.available ? state.assessment.diagnosis[0] : undefined;
  const gt = s.ground_truth;

  return (
    <div className="space-y-6">
      <PageHeader
        index="01"
        section="Mission Control"
        title={s.scenario_title}
        description={state.scenario?.description}
        meta={
          <>
            {s.failed ? (
              <Badge tone="rose">Failed · {s.failure_mode}</Badge>
            ) : !s.running ? (
              <Badge tone="amber">{gt.in_maintenance ? "In maintenance" : "Stopped"}</Badge>
            ) : (
              <Badge tone="emerald">Running</Badge>
            )}
            {s.fault_injected && <Badge tone="rose">Fault injected</Badge>}
            <Badge tone="slate">Seed {s.seed}</Badge>
            {s.busy && (
              <Badge tone="violet">
                <Spinner className="h-2.5 w-2.5" /> {s.busy}
              </Badge>
            )}
          </>
        }
        actions={
          <>
            <select
              className={inputClass}
              value={s.speed}
              onChange={(e) => run("speed", () => api.control(s.session_id, "set_speed", Number(e.target.value)))}
              aria-label="Simulation speed"
            >
              {[...new Set([...SPEEDS, s.speed])].sort((a, b) => a - b).map((v) => (
                <option key={v} value={v}>
                  {v}× real time
                </option>
              ))}
            </select>
            {s.paused ? (
              <Button
                onClick={() => run("resume", () => api.control(s.session_id, "resume"))}
                disabled={s.failed || pending !== null}
              >
                Resume
              </Button>
            ) : (
              <Button onClick={() => run("pause", () => api.control(s.session_id, "pause"))} disabled={pending !== null}>
                Pause
              </Button>
            )}
            <Button
              variant="danger"
              onClick={() => run("inject", () => api.inject(s.session_id))}
              disabled={s.fault_injected || s.scenario === "healthy" || s.failed || pending !== null}
              title="Activate this scenario's fault now"
            >
              {pending === "inject" && <Spinner />} Inject fault
            </Button>
            <Button variant="primary" onClick={() => router.push("/agent")}>
              Analyze with agent
            </Button>
            <span className="mx-1 h-5 w-px bg-slate-800" />
            <Button variant="ghost" onClick={() => void endSession()}>
              New session
            </Button>
          </>
        }
      />
      {s.paused && s.pause_reason && <Notice tone="amber">Simulation paused: {s.pause_reason}</Notice>}
      {error && <Notice tone="rose">{error}</Notice>}

      <div className="grid grid-cols-2 gap-px overflow-hidden rounded-md border border-slate-800 bg-slate-800 lg:grid-cols-5">
        <Stat label="Winding temp" value={num(T, 1)} unit="°C" provenance="observed" tone={T !== null && T >= 130 ? (T >= 145 ? "bad" : "warn") : undefined} hint="alarm 130 · limit 155" />
        <Stat label="Vibration RMS" value={num(vib, 2)} unit="mm/s" provenance="observed" tone={vib !== null && vib >= 4.5 ? (vib >= 7.1 ? "bad" : "warn") : undefined} hint="alarm 4.5 · trip 7.1" />
        <Stat label="Load" value={num(load, 0)} unit="%" provenance="observed" tone={load !== null && load > 100 ? "warn" : undefined} hint={`load ×${s.actuators.load_multiplier.toFixed(2)} · speed ×${s.actuators.speed_setpoint.toFixed(2)}`} />
        <Stat label="Risk ≤ 60 min" value={pct(risk60, 1)} provenance="ml_prediction" tone={risk60 !== null && risk60 >= 0.2 ? (risk60 >= 0.5 ? "bad" : "warn") : undefined} hint="calibrated XGBoost" />
        <Stat label="Likely cause" value={<span className="font-sans text-[20px] font-medium tracking-[-0.01em]">{top ? DIAGNOSIS_LABEL[top.label] ?? top.label : "—"}</span>} provenance="ml_prediction" hint={top ? `p = ${pct(top.probability)}` : undefined} />
      </div>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_380px]">
        <div className="space-y-6">
          <Card
            title="Live telemetry"
            subtitle="Simulated sensors over SSE · 10 s sampling · dropouts and spikes shown as gaps"
            actions={
              <>
                <ProvenanceTag kind="observed" />
                <Segmented options={WINDOWS} value={windowMin} onChange={setWindowMin} format={(w) => `${w}m`} />
              </>
            }
          >
            <div className="grid gap-x-8 gap-y-6 lg:grid-cols-2">
              <div>
                <ChartLabel>Winding temperature · °C</ChartLabel>
                <TelemetryChart samples={state.samples} events={state.events} windowMin={windowMin} metric="T" />
              </div>
              <div>
                <ChartLabel>Vibration RMS · mm/s</ChartLabel>
                <TelemetryChart samples={state.samples} events={state.events} windowMin={windowMin} metric="vib" />
              </div>
              <div>
                <ChartLabel>Load · % rated torque</ChartLabel>
                <TelemetryChart samples={state.samples} events={state.events} windowMin={windowMin} metric="load" height={150} />
              </div>
              <div>
                <ChartLabel>Current · A</ChartLabel>
                <TelemetryChart samples={state.samples} events={state.events} windowMin={windowMin} metric="I" height={150} />
              </div>
            </div>
          </Card>
          <Card
            title="Predicted failure risk"
            subtitle="Calibrated probability of a simulated failure within each horizon, assessed every simulated minute"
            actions={<ProvenanceTag kind="ml_prediction" />}
          >
            <RiskChart risk={state.risk} windowMin={windowMin} />
          </Card>
        </div>
        <div className="space-y-6">
          <Card title="Model assessment" subtitle="Anomaly, change points, diagnosis and risk">
            <AssessmentPanel a={state.assessment} />
          </Card>
          <Card title="Event log" subtitle="Faults, interventions, maintenance and failures" flush>
            {state.events.length === 0 ? (
              <p className="px-5 py-4 text-[13px] text-slate-500">No events yet.</p>
            ) : (
              <ol className="max-h-72 divide-y divide-slate-800 overflow-y-auto">
                {[...state.events].reverse().map((e) => (
                  <li key={e.seq} className="flex gap-4 px-5 py-2.5 text-[12px]">
                    <span className="w-12 shrink-0 font-mono tabular-nums text-slate-500">
                      {simClock(e.t_s).slice(0, 5)}
                    </span>
                    <span className="min-w-0 text-slate-300">
                      {e.summary}
                      <span className="ml-1.5 font-mono text-[10.5px] uppercase tracking-[0.06em] text-slate-600">{e.source}</span>
                      {e.payload?.verified === true && <span className="ml-2"><ProvenanceTag kind="verified" /></span>}
                      {e.payload?.note ? <span className="mt-0.5 block text-amber-300/80">{String(e.payload.note)}</span> : null}
                    </span>
                  </li>
                ))}
              </ol>
            )}
          </Card>
          <Card
            title="Hidden ground truth"
            subtitle="Simulator internals for judging the system; never visible to the models or agent"
            actions={
              <Button variant="ghost" className="h-7 px-2 text-[12px]" onClick={() => setShowTruth((v) => !v)}>
                {showTruth ? "Hide" : "Reveal"}
              </Button>
            }
          >
            {showTruth ? (
              <div className="space-y-3">
                <dl className="divide-y divide-slate-800 text-[12px]">
                  {[
                    ["Cooling efficiency", num(gt.cooling_efficiency, 3)],
                    ["Bearing health", num(gt.bearing_health, 3)],
                    ["Operating hours", num(gt.operating_hours, 2)],
                    ["Failure", gt.failed ? gt.failure_mode : "none"],
                  ].map(([k, v]) => (
                    <div key={k} className="flex justify-between py-1.5">
                      <dt className="text-slate-500">{k}</dt>
                      <dd className="font-mono tabular-nums text-slate-200">{v}</dd>
                    </div>
                  ))}
                </dl>
                <ProvenanceTag kind="ground_truth" />
              </div>
            ) : (
              <p className="text-[12px] text-slate-500">Hidden by default so the demo shows only what the system can observe.</p>
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}
