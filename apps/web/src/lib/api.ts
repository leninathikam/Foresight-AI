import type {
  Action,
  AgentTrace,
  Diagnostics,
  FutureComparison,
  Health,
  ProviderName,
  ReplayCheck,
  RiskAssessment,
  ScenarioId,
  ScenarioInfo,
  SessionSnapshot,
  SessionStatus,
  StateEstimate,
  TelemetryEvent,
  VerificationResult,
} from "./types";

// The browser talks to the FastAPI service directly. No credentials ever reach the client:
// model provider keys live only in the API process.
export const API_BASE_URL = (
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000"
).replace(/\/$/, "");

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(
  path: string,
  init: RequestInit & { timeoutMs?: number } = {},
): Promise<T> {
  const { timeoutMs = 30_000, ...rest } = init;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(`${API_BASE_URL}${path}`, {
      ...rest,
      signal: controller.signal,
      headers: rest.body ? { "Content-Type": "application/json" } : undefined,
      cache: "no-store",
    });
    if (!res.ok) {
      let detail = res.statusText;
      try {
        const body = (await res.json()) as { detail?: unknown };
        if (typeof body.detail === "string") detail = body.detail;
        else if (body.detail) detail = JSON.stringify(body.detail);
      } catch {
        // non-JSON error body
      }
      throw new ApiError(detail, res.status);
    }
    return (await res.json()) as T;
  } catch (err) {
    if (err instanceof ApiError) throw err;
    if (err instanceof DOMException && err.name === "AbortError") {
      throw new ApiError(`Request timed out after ${timeoutMs / 1000}s`, 0);
    }
    throw new ApiError(
      `Cannot reach the Foresight API at ${API_BASE_URL}. Is it running?`,
      0,
    );
  } finally {
    clearTimeout(timer);
  }
}

const post = <T>(path: string, body?: unknown, timeoutMs?: number) =>
  request<T>(path, {
    method: "POST",
    body: body === undefined ? undefined : JSON.stringify(body),
    timeoutMs,
  });

export const api = {
  health: () => request<Health>("/api/health", { timeoutMs: 5_000 }),
  diagnostics: () => request<Diagnostics>("/api/diagnostics"),
  modelCheck: (provider?: ProviderName) =>
    post<Record<string, unknown>>(
      `/api/diagnostics/model-check${provider ? `?provider=${provider}` : ""}`,
      undefined,
      120_000,
    ),
  scenarios: () => request<ScenarioInfo[]>("/api/scenarios"),
  evaluation: () => request<Record<string, unknown>>("/api/evaluation"),
  redteam: () => request<Record<string, unknown>>("/api/redteam"),

  createSession: (scenario: ScenarioId, seed: number, speed?: number) =>
    post<SessionSnapshot>("/api/sessions", { scenario, seed, speed }, 60_000),
  snapshot: (id: string) => request<SessionSnapshot>(`/api/sessions/${id}`),
  deleteSession: (id: string) => request<unknown>(`/api/sessions/${id}`, { method: "DELETE" }),
  streamUrl: (id: string) => `${API_BASE_URL}/api/sessions/${id}/stream`,
  control: (id: string, action: "pause" | "resume" | "set_speed", speed?: number) =>
    post<SessionStatus>(`/api/sessions/${id}/control`, { action, speed }),
  inject: (id: string) => post<TelemetryEvent>(`/api/sessions/${id}/inject`),
  assessment: (id: string) => request<RiskAssessment>(`/api/sessions/${id}/assessment`),
  estimate: (id: string) => request<StateEstimate>(`/api/sessions/${id}/estimate`),
  futures: (
    id: string,
    body: {
      actions: Action[];
      horizon_min: number;
      members: number;
      state_source: "estimated" | "oracle";
    },
  ) => post<FutureComparison>(`/api/sessions/${id}/futures`, body, 180_000),
  comparison: (id: string, cid: string) =>
    request<FutureComparison>(`/api/sessions/${id}/futures/${cid}`),
  verify: (id: string, action: Action, comparisonId: string | null, claimed = "unknown") =>
    post<VerificationResult>(`/api/sessions/${id}/verify`, {
      action,
      comparison_id: comparisonId,
      claimed_failure_mode: claimed,
    }),
  startAgent: (id: string, opts?: { provider?: ProviderName; reasoning_effort?: string }) =>
    post<{ run_id: string; provider: string; notice: string | null }>(
      `/api/sessions/${id}/agent/runs`,
      opts ?? {},
    ),
  agentRun: (id: string, runId: string) =>
    request<AgentTrace>(`/api/sessions/${id}/agent/runs/${runId}`),
  intervene: (
    id: string,
    body: {
      action: Action;
      approved: boolean;
      source: "user" | "agent";
      comparison_id: string | null;
    },
  ) =>
    post<{ event: TelemetryEvent; verification: VerificationResult | null }>(
      `/api/sessions/${id}/interventions`,
      body,
    ),
  replayCheck: (id: string) =>
    request<ReplayCheck>(`/api/sessions/${id}/replay-check`, { timeoutMs: 120_000 }),
};
