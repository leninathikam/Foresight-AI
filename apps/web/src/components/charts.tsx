"use client";

import {
  Area,
  Bar,
  BarChart,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { downsample } from "@/lib/format";
import type { BranchOutcome, CompactSample, RiskPoint, TelemetryEvent } from "@/lib/types";

export const PALETTE = {
  neutral: "#8f8f8a",
  faint: "#52524f",
  accent: "#7096fa",
  thermal: "#dba552",
  model: "#9e94d2",
  ok: "#5fbf93",
  warn: "#dba552",
  bad: "#e2716d",
  steel: "#7ea5cf",
} as const;

const GRID = "rgba(143,143,138,0.10)";
const AXIS = {
  stroke: "#3a3a3c",
  tick: { fill: "#6f6f6b", fontSize: 10.5 },
  tickLine: false,
  fontSize: 10.5,
};
const TOOLTIP = {
  contentStyle: {
    background: "#18181b",
    border: "1px solid #3a3a3c",
    borderRadius: 4,
    fontSize: 12,
    fontFamily: "var(--font-mono)",
    boxShadow: "0 8px 24px rgba(0,0,0,0.4)",
  },
  labelStyle: { color: "#b3b3ae" },
  cursor: { stroke: "#52524f", strokeWidth: 1 },
};
export const BRANCH_COLORS = ["#8f8f8a", "#7096fa", "#dba552", "#5fbf93", "#9e94d2", "#e2716d", "#7ea5cf"];

function minutesLabel(v: number) {
  return `${Math.round(v)}m`;
}

export interface TelemetryChartProps {
  samples: CompactSample[];
  events: TelemetryEvent[];
  windowMin: number;
  metric: "T" | "vib" | "load" | "I";
  height?: number;
}

const METRIC = {
  T: { name: "Winding temperature (°C)", color: PALETTE.thermal, limits: [130, 155] },
  vib: { name: "Vibration RMS (mm/s)", color: PALETTE.accent, limits: [4.5, 7.1] },
  load: { name: "Load (% rated)", color: "#b3b3ae", limits: [100] },
  I: { name: "Current (A)", color: PALETTE.steel, limits: [] as number[] },
} as const;

export function TelemetryChart({ samples, events, windowMin, metric, height = 200 }: TelemetryChartProps) {
  const last = samples.length ? samples[samples.length - 1].t : 0;
  const from = last - windowMin * 60;
  const data = downsample(
    samples
      .filter((s) => s.t >= from)
      .map((s) => ({ m: s.t / 60, v: s[metric] })),
    480,
  );
  const cfg = METRIC[metric];
  const marks = events.filter((e) => e.t_s >= from && e.kind !== "note");
  return (
    <div style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
          <CartesianGrid stroke={GRID} vertical={false} />
          <XAxis
            dataKey="m"
            type="number"
            domain={["dataMin", "dataMax"]}
            tickFormatter={minutesLabel}
            {...AXIS}
          />
          <YAxis domain={["auto", "auto"]} {...AXIS} width={44} />
          <Tooltip
            {...TOOLTIP}
            labelFormatter={(v) => `t = ${Number(v).toFixed(1)} min`}
            formatter={(v) => [typeof v === "number" ? v.toFixed(2) : "missing", cfg.name]}
          />
          {cfg.limits.map((l, i) => (
            <ReferenceLine
              key={l}
              y={l}
              stroke={i === cfg.limits.length - 1 ? PALETTE.bad : PALETTE.warn}
              strokeOpacity={0.55}
              strokeDasharray="3 4"
              label={{
                value: i === cfg.limits.length - 1 ? `trip ${l}` : `alarm ${l}`,
                fill: "#6f6f6b",
                fontSize: 10,
                fontFamily: "var(--font-mono)",
                position: "insideTopRight",
              }}
            />
          ))}
          {marks.map((e) => (
            <ReferenceLine
              key={e.seq}
              x={e.t_s / 60}
              stroke={e.kind === "fault_injected" || e.kind === "failure" ? PALETTE.bad : PALETTE.neutral}
              strokeOpacity={0.5}
              strokeDasharray="2 3"
            />
          ))}
          <Line
            dataKey="v"
            stroke={cfg.color}
            strokeWidth={1.25}
            dot={false}
            isAnimationActive={false}
            connectNulls={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

export function RiskChart({ risk, windowMin, height = 200 }: { risk: RiskPoint[]; windowMin: number; height?: number }) {
  const last = risk.length ? risk[risk.length - 1].t : 0;
  const data = risk
    .filter((p) => p.t >= last - windowMin * 60)
    .map((p) => ({
      m: p.t / 60,
      r15: p.available ? p.risk15 : null,
      r30: p.available ? p.risk30 : null,
      r60: p.available ? p.risk60 : null,
    }));
  return (
    <div style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={downsample(data, 400)} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
          <CartesianGrid stroke={GRID} vertical={false} />
          <XAxis dataKey="m" type="number" domain={["dataMin", "dataMax"]} tickFormatter={minutesLabel} {...AXIS} />
          <YAxis domain={[0, 1]} tickFormatter={(v) => `${Math.round(v * 100)}%`} {...AXIS} width={44} />
          <Tooltip
            {...TOOLTIP}
            labelFormatter={(v) => `t = ${Number(v).toFixed(0)} min`}
            formatter={(v, n) => [typeof v === "number" ? `${(v * 100).toFixed(1)}%` : "n/a", n]}
          />
          <Legend wrapperStyle={{ fontSize: 11 }} iconType="plainline" />
          <Line name="P(fail = 15 min)" dataKey="r15" stroke={PALETTE.bad} dot={false} strokeWidth={1.4} isAnimationActive={false} />
          <Line name="= 30 min" dataKey="r30" stroke={PALETTE.warn} dot={false} strokeWidth={1.4} isAnimationActive={false} />
          <Line name="= 60 min" dataKey="r60" stroke={PALETTE.neutral} dot={false} strokeWidth={1.4} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

export function BranchBandChart({
  branches,
  selected,
  metric,
  height = 280,
}: {
  branches: BranchOutcome[];
  selected: string | null;
  metric: "temperature" | "vibration";
  height?: number;
}) {
  const key = metric === "temperature" ? "temperature_band" : "vibration_band";
  const base = branches[0]?.[key];
  if (!base) return null;
  const data = base.t_min.map((t, i) => {
    const row: Record<string, number | [number, number]> = { t };
    for (const b of branches) {
      const band = b[key];
      row[b.branch_id] = band.p50[i];
      if (b.branch_id === selected) row.band = [band.p10[i], band.p90[i]];
    }
    return row;
  });
  const limits = metric === "temperature" ? [130, 155] : [4.5, 7.1];
  return (
    <div style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
          <CartesianGrid stroke={GRID} vertical={false} />
          <XAxis dataKey="t" type="number" domain={[0, "dataMax"]} tickFormatter={(v) => `+${Math.round(v)}m`} {...AXIS} />
          <YAxis domain={["auto", "auto"]} {...AXIS} width={44} />
          <Tooltip {...TOOLTIP} labelFormatter={(v) => `+${Number(v).toFixed(0)} min`} formatter={(v, n) => {
            const label = n === "band" ? "p10–p90 (selected)" : branches.find((b) => b.branch_id === n)?.label ?? String(n);
            const text = Array.isArray(v) ? `${Number(v[0]).toFixed(1)} – ${Number(v[1]).toFixed(1)}` : Number(v).toFixed(1);
            return [text, label];
          }} />
          {limits.map((l, i) => (
            <ReferenceLine key={l} y={l} stroke={i ? PALETTE.bad : PALETTE.warn} strokeOpacity={0.55} strokeDasharray="3 4" />
          ))}
          {selected && (
            <Area dataKey="band" stroke="none" fill={PALETTE.accent} fillOpacity={0.1} isAnimationActive={false} />
          )}
          {branches.map((b, i) => (
            <Line
              key={b.branch_id}
              dataKey={b.branch_id}
              name={b.branch_id}
              stroke={BRANCH_COLORS[i % BRANCH_COLORS.length]}
              strokeWidth={b.branch_id === selected ? 2.4 : 1.3}
              strokeDasharray={b.branch_id === "baseline" ? "5 4" : undefined}
              dot={false}
              isAnimationActive={false}
            />
          ))}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

const UNIT_TICKS = [0, 0.25, 0.5, 0.75, 1];

export function ReliabilityChart({
  series,
  height = 240,
}: {
  series: { name: string; color: string; points: { mean_predicted: number | null; observed_frequency: number | null; count: number }[] }[];
  height?: number;
}) {
  return (
    <div style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
          <CartesianGrid stroke={GRID} />
          <XAxis dataKey="x" type="number" domain={[0, 1]} ticks={UNIT_TICKS} tickFormatter={(v) => v.toFixed(2)} {...AXIS} name="predicted" />
          <YAxis dataKey="y" type="number" domain={[0, 1]} ticks={UNIT_TICKS} tickFormatter={(v) => v.toFixed(2)} {...AXIS} width={40} name="observed" />
          <Tooltip {...TOOLTIP} formatter={(v) => Number(v).toFixed(3)} />
          <Legend wrapperStyle={{ fontSize: 11 }} />
          <Line
            data={[{ x: 0, y: 0 }, { x: 1, y: 1 }]}
            dataKey="y"
            name="perfect calibration"
            stroke="#52524f"
            strokeDasharray="3 4"
            dot={false}
            isAnimationActive={false}
          />
          {series.map((s) => (
            <Scatter
              key={s.name}
              name={s.name}
              data={s.points
                .filter((p) => p.mean_predicted !== null && p.observed_frequency !== null)
                .map((p) => ({ x: p.mean_predicted, y: p.observed_frequency, n: p.count }))}
              fill={s.color}
              line={{ stroke: s.color }}
              isAnimationActive={false}
            />
          ))}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

export function SimpleBarChart({
  data,
  bars,
  height = 240,
  yFormatter,
}: {
  data: Record<string, string | number | null>[];
  bars: { key: string; name: string; color: string }[];
  height?: number;
  yFormatter?: (v: number) => string;
}) {
  return (
    <div style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
          <CartesianGrid stroke={GRID} vertical={false} />
          <XAxis dataKey="name" {...AXIS} interval={0} />
          <YAxis {...AXIS} tickFormatter={yFormatter} width={56} />
          <Tooltip {...TOOLTIP} formatter={(v) => (typeof v === "number" && yFormatter ? yFormatter(v) : v)} />
          {bars.length > 1 && <Legend wrapperStyle={{ fontSize: 11 }} />}
          {bars.map((b) => (
            <Bar key={b.key} dataKey={b.key} name={b.name} fill={b.color} radius={[2, 2, 0, 0]} maxBarSize={36} isAnimationActive={false} />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
