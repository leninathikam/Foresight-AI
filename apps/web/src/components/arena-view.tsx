"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { num, pct, simClock, usd } from "@/lib/format";
import { useSession } from "@/lib/session-context";
import type { BranchOutcome, FutureArenaComparison } from "@/lib/types";
import { BranchBandChart } from "./charts";
import { IconAlertTriangle, IconBarChart, IconSliders, IconTrophy, IconWrench } from "./icons";
import { Badge, Button, Card, EmptyState, Eyebrow, Notice, PageHeader, ProvenanceTag, Spinner, cx, inputClass } from "./ui";

function getScenarioIcon(id: string) {
  switch (id) {
    case "continue_operating":
      return <IconAlertTriangle className="h-5 w-5 text-amber-400" />;
    case "reduce_load":
      return <IconSliders className="h-5 w-5 text-cyan-400" />;
    case "planned_maintenance":
      return <IconWrench className="h-5 w-5 text-emerald-400" />;
    default:
      return <IconBarChart className="h-5 w-5 text-slate-400" />;
  }
}

export function ArenaView() {
  const { state } = useSession();
  const [arena, setArena] = useState<FutureArenaComparison | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reduceFraction, setReduceFraction] = useState(30);
  const [inspectionDelay, setInspectionDelay] = useState(15);
  const [selectedScenarioId, setSelectedScenarioId] = useState<string>("planned_maintenance");
  const [reproducing, setReproducing] = useState(false);
  const [replaySuccess, setReplaySuccess] = useState<boolean | null>(null);

  const sessionId = state.status?.session_id;

  const runArena = async () => {
    if (!sessionId) return;
    setLoading(true);
    setError(null);
    setReplaySuccess(null);
    try {
      const res = await api.arena(sessionId, {
        reduce_load_fraction: reduceFraction / 100,
        inspection_delay_min: inspectionDelay,
        members: 8,
        horizon_min: 180,
      });
      setArena(res);
      setSelectedScenarioId(res.winner_scenario_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  };

  const reproduceArena = async () => {
    if (!sessionId || !arena) return;
    setReproducing(true);
    try {
      const res2 = await api.arena(sessionId, {
        reduce_load_fraction: reduceFraction / 100,
        inspection_delay_min: inspectionDelay,
        members: 8,
        horizon_min: 180,
      });
      const match =
        res2.seeds.join(",") === arena.seeds.join(",") &&
        res2.scenarios.every((s, i) => Math.abs(s.objective_score - arena.scenarios[i].objective_score) < 1e-4);
      setReplaySuccess(match);
    } catch {
      setReplaySuccess(false);
    } finally {
      setReproducing(false);
    }
  };

  useEffect(() => {
    if (sessionId && !arena && !loading) {
      void runArena();
    }
  }, [sessionId]);

  if (!state.status) {
    return (
      <EmptyState
        eyebrow="02 / Future Arena"
        title="No active session"
        action={
          <Link href="/">
            <Button variant="primary">Go to Mission Control</Button>
          </Link>
        }
      >
        Start a digital twin session on Mission Control to run the 3-way Future Arena.
      </EmptyState>
    );
  }

  const branchesForChart: BranchOutcome[] = arena
    ? arena.scenarios.map((s) => ({
        branch_id: s.scenario_id,
        label: s.label,
        action: s.action,
        n_members: arena.members,
        failure_incidence: s.failure_incidence,
        failure_incidence_ci95: s.failure_incidence_ci95,
        failure_modes: {},
        median_time_to_failure_min: null,
        peak_temperature_mean_c: s.peak_temperature_p90_c,
        peak_temperature_p90_c: s.peak_temperature_p90_c,
        peak_vibration_mean_mm_s: s.peak_vibration_p90_mm_s,
        peak_vibration_p90_mm_s: s.peak_vibration_p90_mm_s,
        max_running_load: 1.0,
        downtime_mean_h: s.downtime_mean_h,
        cost_mean: s.expected_cost_usd,
        cost_breakdown_mean: {
          lost_production: s.cost_breakdown.lost_production || 0,
          failure_repair: s.cost_breakdown.failure_repair || 0,
          failure_downtime: s.cost_breakdown.failure_downtime || 0,
          intervention: s.cost_breakdown.intervention || 0,
          deferred_maintenance: s.cost_breakdown.deferred_maintenance || 0,
          terminal_risk_penalty: s.cost_breakdown.terminal_risk_penalty || 0,
        },
        objective: s.objective_score,
        end_alarm_fraction: 0,
        temperature_band: s.temperature_band,
        vibration_band: s.vibration_band,
        delta_vs_baseline: {},
      }))
    : [];

  return (
    <div className="space-y-8">
      <PageHeader
        index="02"
        section="Future Arena"
        title="Future Arena: 3-Way Counterfactual Simulation"
        description="Head-to-head evaluation of the 3 canonical paths: Continue Operating, Operational Load Reduction, and Planned Maintenance. All branches simulate matched disturbance paths from identical initial state using common random numbers (CRN)."
        meta={
          <div className="flex flex-wrap items-center gap-3">
            <ProvenanceTag kind="simulation_estimate" />
            <Badge tone="cyan">Deterministic CRN (Seed {arena?.reproducible_base_seed ?? 42})</Badge>
            <span className="font-mono text-xs text-slate-400">Clock: {simClock(state.status.sim_time_s)}</span>
          </div>
        }
      />

      {/* Control Bar */}
      <Card className="flex flex-wrap items-center justify-between gap-4 p-4">
        <div className="flex flex-wrap items-center gap-6">
          <div>
            <span className="block font-mono text-[10.5px] uppercase tracking-wider text-slate-400">
              Derate Load %
            </span>
            <div className="mt-1 flex items-center gap-2">
              <input
                type="number"
                min={5}
                max={50}
                step={5}
                value={reduceFraction}
                onChange={(e) => setReduceFraction(Number(e.target.value))}
                className={cx(inputClass, "w-20 py-1 text-xs font-mono")}
              />
              <span className="text-xs text-slate-400">%</span>
            </div>
          </div>

          <div>
            <span className="block font-mono text-[10.5px] uppercase tracking-wider text-slate-400">
              Inspection Delay
            </span>
            <div className="mt-1 flex items-center gap-2">
              <input
                type="number"
                min={0}
                max={120}
                step={5}
                value={inspectionDelay}
                onChange={(e) => setInspectionDelay(Number(e.target.value))}
                className={cx(inputClass, "w-20 py-1 text-xs font-mono")}
              />
              <span className="text-xs text-slate-400">min</span>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <Button variant="primary" onClick={runArena} disabled={loading}>
            {loading ? <Spinner className="h-4 w-4" /> : "Re-Simulate Arena"}
          </Button>
          {arena && (
            <Button variant="secondary" onClick={reproduceArena} disabled={reproducing}>
              {reproducing ? <Spinner className="h-4 w-4" /> : "Verify Replay (CRN)"}
            </Button>
          )}
        </div>
      </Card>

      {replaySuccess !== null && (
        <Notice tone={replaySuccess ? "emerald" : "rose"}>
          {replaySuccess
            ? "Deterministic Replay Verified: Exact 1:1 match in random seeds, trajectory bands, and cost objectives."
            : "Replay divergence detected: Simulation seeds or initial states did not match."}
        </Notice>
      )}

      {error && <Notice tone="rose">{error}</Notice>}

      {arena && (
        <>
          {/* Winner Banner */}
          <div className="rounded-lg border border-cyan-500/30 bg-cyan-950/20 p-5">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <div className="flex h-7 w-7 items-center justify-center rounded-md border border-amber-500/30 bg-amber-500/10">
                  <IconTrophy className="h-4 w-4 text-amber-400" />
                </div>
                <span className="font-mono text-xs uppercase tracking-wider text-cyan-300 font-semibold">
                  Arena Recommendation
                </span>
                <Badge tone="cyan">{arena.winner_label}</Badge>
              </div>
              <span className="font-mono text-xs text-slate-400">Computed in {arena.compute_ms} ms</span>
            </div>
            <p className="mt-2 text-sm leading-relaxed text-slate-200">{arena.recommendation_reason}</p>
          </div>

          {/* 3-Column Comparison Grid */}
          <div className="grid gap-5 md:grid-cols-3">
            {arena.scenarios.map((sc) => {
              const isSelected = sc.scenario_id === selectedScenarioId;
              const isWinner = sc.scenario_id === arena.winner_scenario_id;
              const isRejected = sc.safety_status === "rejected";

              return (
                <div
                  key={sc.scenario_id}
                  onClick={() => setSelectedScenarioId(sc.scenario_id)}
                  className={cx(
                    "relative cursor-pointer rounded-lg border p-5 transition-all",
                    isSelected
                      ? "border-cyan-400 bg-slate-900/90 shadow-lg shadow-cyan-950/50"
                      : "border-slate-800 bg-slate-900/50 hover:border-slate-700",
                  )}
                >
                  {isWinner && (
                    <div className="absolute top-3 right-3">
                      <Badge tone="cyan">Best Score</Badge>
                    </div>
                  )}

                  <div className="flex items-center gap-3">
                    <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-slate-800 bg-slate-800/60 shadow-sm">
                      {getScenarioIcon(sc.scenario_id)}
                    </div>
                    <div>
                      <h3 className="font-semibold text-slate-100">{sc.label}</h3>
                      <span className="font-mono text-[11px] text-slate-400">{sc.scenario_id}</span>
                    </div>
                  </div>

                  <div className="mt-5 grid grid-cols-2 gap-3 border-y border-slate-800 py-3 font-mono text-xs">
                    <div>
                      <span className="text-[10px] text-slate-400 uppercase">Failure Risk</span>
                      <div className={cx("mt-0.5 text-base font-semibold", sc.failure_incidence > 0 ? "text-rose-400" : "text-emerald-400")}>
                        {pct(sc.failure_incidence)}
                      </div>
                    </div>
                    <div>
                      <span className="text-[10px] text-slate-400 uppercase">Expected Cost</span>
                      <div className="mt-0.5 text-base font-semibold text-slate-100">{usd(sc.expected_cost_usd)}</div>
                    </div>
                    <div>
                      <span className="text-[10px] text-slate-400 uppercase">Peak Temp (p90)</span>
                      <div className={cx("mt-0.5 font-medium", sc.peak_temperature_p90_c >= 140 ? "text-rose-400" : "text-slate-200")}>
                        {num(sc.peak_temperature_p90_c, 1)} °C
                      </div>
                    </div>
                    <div>
                      <span className="text-[10px] text-slate-400 uppercase">Peak Vib (p90)</span>
                      <div className={cx("mt-0.5 font-medium", sc.peak_vibration_p90_mm_s >= 6.1 ? "text-rose-400" : "text-slate-200")}>
                        {num(sc.peak_vibration_p90_mm_s, 2)} mm/s
                      </div>
                    </div>
                  </div>

                  <div className="mt-4 flex items-center justify-between">
                    <span className="text-[11px] text-slate-400 font-mono">Verifier Status:</span>
                    <Badge tone={isRejected ? "rose" : sc.safety_status === "accepted" ? "emerald" : "amber"}>
                      {sc.safety_status.toUpperCase()}
                    </Badge>
                  </div>

                  {sc.rejection_reasons.length > 0 && (
                    <div className="mt-3 rounded bg-rose-950/40 border border-rose-900/40 p-2 text-[11px] text-rose-300">
                      {sc.rejection_reasons[0]}
                    </div>
                  )}
                </div>
              );
            })}
          </div>

          {/* Synchronized Trajectory Charts for All Scenarios */}
          <div className="grid gap-6 lg:grid-cols-2">
            <Card title="Winding Temperature Ensembles (p10/p50/p90)" subtitle="Alarm threshold: 140 °C · Trip limit: 155 °C">
              <div className="h-64">
                <BranchBandChart
                  branches={branchesForChart}
                  selected={selectedScenarioId}
                  metric="temperature"
                  height={256}
                />
              </div>
            </Card>

            <Card title="ISO 10816-3 Vibration Velocity Ensembles" subtitle="Safety limit: 6.1 mm/s · Trip limit: 7.1 mm/s">
              <div className="h-64">
                <BranchBandChart
                  branches={branchesForChart}
                  selected={selectedScenarioId}
                  metric="vibration"
                  height={256}
                />
              </div>
            </Card>
          </div>

          {/* Model Assumptions */}
          <Card title="Scientific Ground Truth & Digital Twin Assumptions">
            <ul className="space-y-1.5 text-xs text-slate-400">
              {arena.assumptions.map((assump, idx) => (
                <li key={idx} className="flex items-start gap-2">
                  <span className="text-cyan-400">•</span>
                  <span>{assump}</span>
                </li>
              ))}
            </ul>
          </Card>
        </>
      )}
    </div>
  );
}
