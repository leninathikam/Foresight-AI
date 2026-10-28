"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useReducer,
  useRef,
  type ReactNode,
} from "react";
import { api, ApiError } from "./api";
import type {
  AgentStage,
  AgentTrace,
  CompactSample,
  RiskAssessment,
  RiskPoint,
  ScenarioId,
  ScenarioInfo,
  SessionSnapshot,
  SessionStatus,
  TelemetryEvent,
  TickMessage,
} from "./types";

const STORAGE_KEY = "foresight.session-id";
const MAX_SAMPLES = 8640;

export type Connection = "idle" | "connecting" | "live" | "reconnecting" | "error";

export interface AgentProgress {
  run_id: string;
  stage: AgentStage;
  status: AgentTrace["status"];
  steps: number;
}

interface State {
  sessionId: string | null;
  status: SessionStatus | null;
  scenario: ScenarioInfo | null;
  samples: CompactSample[];
  risk: RiskPoint[];
  assessment: RiskAssessment | null;
  events: TelemetryEvent[];
  agent: Record<string, AgentProgress>;
  latestRunId: string | null;
  connection: Connection;
  error: string | null;
  /** Wall-clock ms of the last message from the stream (for staleness display). */
  lastMessageAt: number | null;
}

type Msg =
  | { type: "loading"; sessionId: string }
  | { type: "snapshot"; snap: SessionSnapshot; at: number }
  | { type: "tick"; tick: TickMessage; at: number }
  | { type: "status"; status: SessionStatus; at: number }
  | { type: "agent"; progress: AgentProgress; at: number }
  | { type: "connection"; connection: Connection; error?: string | null }
  | { type: "cleared"; error?: string | null };

const initial: State = {
  sessionId: null,
  status: null,
  scenario: null,
  samples: [],
  risk: [],
  assessment: null,
  events: [],
  agent: {},
  latestRunId: null,
  connection: "idle",
  error: null,
  lastMessageAt: null,
};

function mergeEvents(prev: TelemetryEvent[], next: TelemetryEvent[]): TelemetryEvent[] {
  if (!next.length) return prev;
  const seen = new Set(prev.map((e) => e.seq));
  return [...prev, ...next.filter((e) => !seen.has(e.seq))];
}

function reducer(state: State, msg: Msg): State {
  switch (msg.type) {
    case "loading":
      return { ...initial, sessionId: msg.sessionId, connection: "connecting" };
    case "snapshot": {
      const runs = msg.snap.agent_runs;
      return {
        ...state,
        sessionId: msg.snap.status.session_id,
        status: msg.snap.status,
        scenario: msg.snap.scenario,
        samples: msg.snap.samples.slice(-MAX_SAMPLES),
        risk: msg.snap.risk_history,
        assessment: msg.snap.assessment,
        events: msg.snap.events,
        latestRunId: runs.length ? runs[runs.length - 1].run_id : state.latestRunId,
        error: null,
        lastMessageAt: msg.at,
      };
    }
    case "tick": {
      const { tick } = msg;
      const lastSeq = state.samples.length ? state.samples[state.samples.length - 1].seq : -1;
      const fresh = tick.samples.filter((s) => s.seq > lastSeq);
      const samples = fresh.length
        ? [...state.samples, ...fresh].slice(-MAX_SAMPLES)
        : state.samples;
      const risk =
        tick.risk_point && (!state.risk.length || tick.risk_point.t > state.risk[state.risk.length - 1].t)
          ? [...state.risk, tick.risk_point]
          : state.risk;
      return {
        ...state,
        samples,
        risk,
        assessment: tick.assessment ?? state.assessment,
        events: mergeEvents(state.events, tick.events),
        status: tick.status,
        lastMessageAt: msg.at,
      };
    }
    case "status":
      return { ...state, status: msg.status, lastMessageAt: msg.at };
    case "agent":
      return {
        ...state,
        agent: { ...state.agent, [msg.progress.run_id]: msg.progress },
        latestRunId: msg.progress.run_id,
        lastMessageAt: msg.at,
      };
    case "connection":
      return {
        ...state,
        connection: msg.connection,
        error: msg.error === undefined ? state.error : msg.error,
      };
    case "cleared":
      return { ...initial, error: msg.error ?? null };
  }
}

interface SessionApi {
  state: State;
  startSession: (scenario: ScenarioId, seed: number, speed?: number) => Promise<void>;
  endSession: () => Promise<void>;
  resync: () => Promise<void>;
  noteAgentRun: (runId: string) => void;
}

const SessionContext = createContext<SessionApi | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(reducer, initial);
  const sessionIdRef = useRef<string | null>(null);

  const resyncFor = useCallback(async (id: string) => {
    try {
      const snap = await api.snapshot(id);
      dispatch({ type: "snapshot", snap, at: Date.now() });
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        window.localStorage.removeItem(STORAGE_KEY);
        sessionIdRef.current = null;
        dispatch({ type: "cleared", error: "The previous session has expired." });
      } else {
        dispatch({
          type: "connection",
          connection: "error",
          error: err instanceof Error ? err.message : String(err),
        });
      }
    }
  }, []);

  // Restore a session id from a previous visit.
  useEffect(() => {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    if (!stored) return;
    sessionIdRef.current = stored;
    queueMicrotask(() => dispatch({ type: "loading", sessionId: stored }));
  }, []);

  // Stream subscription for the active session.
  const { sessionId } = state;
  useEffect(() => {
    if (!sessionId) return;
    let closed = false;
    let hadError = false;
    void resyncFor(sessionId);
    const es = new EventSource(api.streamUrl(sessionId));
    es.onopen = () => {
      dispatch({ type: "connection", connection: "live", error: null });
      if (hadError) void resyncFor(sessionId);
      hadError = false;
    };
    es.onerror = () => {
      if (closed) return;
      hadError = true;
      dispatch({ type: "connection", connection: "reconnecting" });
    };
    es.addEventListener("tick", (ev) => {
      dispatch({ type: "tick", tick: JSON.parse((ev as MessageEvent).data), at: Date.now() });
    });
    es.addEventListener("status", (ev) => {
      dispatch({ type: "status", status: JSON.parse((ev as MessageEvent).data), at: Date.now() });
    });
    es.addEventListener("agent", (ev) => {
      dispatch({ type: "agent", progress: JSON.parse((ev as MessageEvent).data), at: Date.now() });
    });
    return () => {
      closed = true;
      es.close();
    };
  }, [sessionId, resyncFor]);

  const startSession = useCallback(async (scenario: ScenarioId, seed: number, speed?: number) => {
    const previous = sessionIdRef.current;
    const snap = await api.createSession(scenario, seed, speed);
    const id = snap.status.session_id;
    window.localStorage.setItem(STORAGE_KEY, id);
    sessionIdRef.current = id;
    dispatch({ type: "loading", sessionId: id });
    dispatch({ type: "snapshot", snap, at: Date.now() });
    if (previous && previous !== id) {
      api.deleteSession(previous).catch(() => undefined);
    }
  }, []);

  const endSession = useCallback(async () => {
    const id = sessionIdRef.current;
    window.localStorage.removeItem(STORAGE_KEY);
    sessionIdRef.current = null;
    dispatch({ type: "cleared" });
    if (id) await api.deleteSession(id).catch(() => undefined);
  }, []);

  const resync = useCallback(async () => {
    if (sessionIdRef.current) await resyncFor(sessionIdRef.current);
  }, [resyncFor]);

  const noteAgentRun = useCallback((runId: string) => {
    dispatch({
      type: "agent",
      progress: { run_id: runId, stage: "OBSERVE", status: "running", steps: 0 },
      at: Date.now(),
    });
  }, []);

  const value = useMemo(
    () => ({ state, startSession, endSession, resync, noteAgentRun }),
    [state, startSession, endSession, resync, noteAgentRun],
  );
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionApi {
  const ctx = useContext(SessionContext);
  if (!ctx) throw new Error("useSession must be used within SessionProvider");
  return ctx;
}
