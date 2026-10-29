"use client";

import { useEffect, useState } from "react";
import { api, API_BASE_URL } from "@/lib/api";
import { useSession } from "@/lib/session-context";
import type { Diagnostics, Health, ReplayCheck } from "@/lib/types";
import { Badge, Button, Card, KeyValue, KeyValueList, Notice, PageHeader, Spinner } from "./ui";

const Row = KeyValue;

export function DiagnosticsView() {
  const { state } = useSession();
  const [health, setHealth] = useState<Health | null>(null);
  const [diag, setDiag] = useState<Diagnostics | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [checks, setChecks] = useState<Record<string, Record<string, unknown>>>({});
  const [replay, setReplay] = useState<ReplayCheck | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all([api.health(), api.diagnostics()])
      .then(([h, d]) => {
        if (cancelled) return;
        setHealth(h);
        setDiag(d);
      })
      .catch((e: Error) => !cancelled && setError(e.message));
    return () => {
      cancelled = true;
    };
  }, []);

  const run = async (label: string, fn: () => Promise<void>) => {
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

  const meta = diag?.predictive_models ?? {};
  return (
    <div className="space-y-6">
      <PageHeader
        index="05"
        section="Diagnostics"
        title="System health"
        description="Service health, model provider configuration with live connectivity checks, and a replay determinism check. API keys are never sent to the browser."
      />
      {error && <Notice tone="rose">{error}</Notice>}
      <div className="grid gap-6 lg:grid-cols-2">
        <Card title="API service" subtitle={API_BASE_URL}>
          {health ? (
            <KeyValueList>
              <Row k="Status" v={health.status} />
              <Row k="Version" v={health.version} />
              <Row k="Model bundle" v={health.model_bundle} />
              <Row k="Active sessions" v={health.active_sessions} />
            </KeyValueList>
          ) : (
            <Spinner />
          )}
        </Card>
        <Card title="Agent runtime" subtitle="Shared by every model provider">
          {diag ? (
            <KeyValueList>
              <Row k="Default provider" v={diag.llm.provider} />
              <Row k="Default reasoning effort" v={diag.llm.reasoning_effort} />
              <Row k="Timeout / retries" v={`${diag.llm.timeout_s} s / ${diag.llm.max_retries}`} />
              <Row k="Max tool calls / revisions" v={`${diag.llm.agent_max_tool_calls} / ${diag.llm.agent_max_revisions}`} />
            </KeyValueList>
          ) : (
            <Spinner />
          )}
        </Card>
        {diag?.providers.map((p) => {
          const result = checks[p.name] ?? p.last_check;
          return (
            <Card
              key={p.name}
              title={p.label}
              subtitle={p.default ? "Default provider · Responses API" : "Responses API"}
              actions={
                <Button
                  onClick={() =>
                    run(`check-${p.name}`, async () => {
                      const r = await api.modelCheck(p.name);
                      setChecks((c) => ({ ...c, [p.name]: r }));
                    })
                  }
                  disabled={!p.configured || busy !== null}
                >
                  {busy === `check-${p.name}` && <Spinner />} Run live check
                </Button>
              }
            >
              <KeyValueList>
                <Row k="API key configured" v={<Badge tone={p.configured ? "emerald" : "amber"}>{p.configured ? "yes" : "no"}</Badge>} />
                <Row k="Base URL" v={p.base_url} />
                <Row k="Model" v={p.model} />
                <Row k="Reasoning efforts" v={p.efforts.join(" · ")} />
                <Row
                  k="Price per 1M tokens"
                  v={`$${p.price_per_m.input} in${p.price_per_m.cached_input != null ? ` · $${p.price_per_m.cached_input} cached` : ""} · $${p.price_per_m.output} out`}
                />
              </KeyValueList>
              {!p.configured && (
                <div className="mt-3">
                  <Notice tone="amber">
                    {p.name === "meta" ? "MODEL_API_KEY" : "FIREWORKS_API_KEY"} is not set on the
                    server, so this provider cannot be selected. No model responses are simulated.
                  </Notice>
                </div>
              )}
              {result && (
                <pre className="mt-4 max-h-60 overflow-auto rounded-[4px] border border-slate-800 bg-slate-950 p-3 font-mono text-[11px] text-slate-300">
                  {JSON.stringify(result, null, 2)}
                </pre>
              )}
            </Card>
          );
        })}
        <Card title="Predictive models" subtitle={diag?.model_path}>
          <KeyValueList>
            {["version", "trained_at", "train_rows", "validation_rows", "train_episodes", "validation_episodes", "xgboost_version", "sklearn_version", "iforest_threshold"].map((k) => (
              <Row key={k} k={k.replaceAll("_", " ")} v={meta[k] === undefined ? "—" : String(meta[k])} />
            ))}
          </KeyValueList>
          {meta.cusum_calibration ? (
            <pre className="mt-4 overflow-auto rounded-[4px] border border-slate-800 bg-slate-950 p-3 font-mono text-[11px] text-slate-400">
              {JSON.stringify(meta.cusum_calibration, null, 2)}
            </pre>
          ) : null}
        </Card>
        <Card
          title="Replay determinism"
          subtitle="Re-runs the session from its seed and intervention log and compares telemetry fingerprints"
          actions={
            <Button
              onClick={() => run("replay", async () => setReplay(await api.replayCheck(state.sessionId!)))}
              disabled={!state.sessionId || busy !== null}
            >
              {busy === "replay" && <Spinner />} Check current session
            </Button>
          }
        >
          {replay ? (
            <KeyValueList>
              <Row k="Deterministic" v={<Badge tone={replay.deterministic ? "emerald" : "rose"}>{replay.deterministic ? "identical" : "MISMATCH"}</Badge>} />
              <Row k="Live fingerprint" v={replay.live_fingerprint.slice(0, 16)} />
              <Row k="Replay fingerprint" v={replay.replay_fingerprint.slice(0, 16)} />
              <Row k="Interventions replayed" v={replay.interventions_replayed} />
              <Row k="Compute" v={`${replay.compute_ms} ms`} />
            </KeyValueList>
          ) : (
            <p className="text-xs text-slate-500">{state.sessionId ? "Not run yet." : "Start a session first."}</p>
          )}
        </Card>
      </div>
    </div>
  );
}
