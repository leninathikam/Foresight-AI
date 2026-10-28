import type { Action } from "./types";

export function simClock(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}`;
}

export function num(v: number | null | undefined, digits = 1): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—";
  return v.toFixed(digits);
}

export function pct(v: number | null | undefined, digits = 0): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—";
  return `${(v * 100).toFixed(digits)}%`;
}

export function usd(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—";
  return v.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
}

export function signed(v: number | null | undefined, digits = 1, unit = ""): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—";
  const s = v.toFixed(digits);
  return `${v > 0 ? "+" : ""}${s}${unit}`;
}

export function describeAction(a: Action): string {
  switch (a.type) {
    case "continue_operation":
      return "Continue operation";
    case "reduce_load":
      return `Reduce load by ${Math.round(a.fraction * 100)}%`;
    case "reduce_speed":
      return `Reduce speed by ${Math.round(a.fraction * 100)}%`;
    case "increase_cooling":
      return `Auxiliary cooling +${Math.round(a.boost * 100)}% airflow`;
    case "schedule_inspection":
      return `Inspection in ${a.delay_minutes} min`;
    case "controlled_shutdown":
      return "Controlled shutdown";
  }
}

/** Evenly thin a series to at most ``max`` points, always keeping the last one. */
export function downsample<T>(items: T[], max: number): T[] {
  if (items.length <= max) return items;
  const step = items.length / max;
  const out: T[] = [];
  for (let i = 0; i < max - 1; i++) out.push(items[Math.floor(i * step)]);
  out.push(items[items.length - 1]);
  return out;
}

export const DIAGNOSIS_LABEL: Record<string, string> = {
  none: "No fault",
  cooling: "Cooling degradation",
  bearing: "Bearing deterioration",
  overload: "Overload",
};
