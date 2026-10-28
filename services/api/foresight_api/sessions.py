"""Live digital-twin sessions: simulation clock, telemetry fan-out, analysis, interventions."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from foresight.agents import AgentOrchestrator, AgentSnapshot, AgentTrace, MetaModelClient
from foresight.branching import (
    ACTION_ADAPTER,
    ActuatorSettings,
    FutureComparison,
    StateEstimate,
    compare_futures,
    estimate_state,
)
from foresight.config import Settings
from foresight.prediction import RiskAssessment, RiskBundle, RiskEngine
from foresight.simulation import (
    SCENARIOS,
    Action,
    ContinueOperation,
    EpisodeConfig,
    ScenarioId,
    canonical_episode,
)
from foresight.telemetry import TelemetryConfig, TelemetrySample, TelemetryStream, replay
from foresight.verification import Proposal, VerificationResult, verify_independently

log = logging.getLogger("foresight.session")

TICK_WALL_S = 0.5
ASSESS_EVERY_SIM_S = 60.0
# Monitor stage: pause once when 60-min risk crosses this, re-arm after it falls back.
ALERT_PAUSE_RISK = 0.5
ALERT_REARM_RISK = 0.2
MAX_SESSIONS = 20
SESSION_IDLE_TTL_S = 2 * 3600


class SessionError(ValueError):
    pass


def compact_sample(s: TelemetrySample) -> dict:
    v = s.values
    return {
        "seq": s.seq,
        "t": s.t_s,
        "T": v["temperature_c"],
        "Ta": v["ambient_c"],
        "vib": v["vibration_mm_s"],
        "rpm": v["speed_rpm"],
        "load": v["load_pct"],
        "I": v["current_a"],
        "V": v["voltage_v"],
        "run": s.running,
        "bad": [k for k, q in s.quality.items() if q != "ok"],
    }


class LiveSession:
    def __init__(
        self, scenario: ScenarioId, seed: int, bundle: RiskBundle, settings: Settings, speed: float
    ) -> None:
        self.id = f"s-{uuid.uuid4().hex[:8]}"
        self.scenario = scenario
        self.seed = seed
        self.settings = settings
        self.created_at = datetime.now(UTC).isoformat(timespec="seconds")
        self.last_active = time.monotonic()
        # The machine starts healthy; the scenario's fault is injected on demand.
        self.episode = EpisodeConfig(scenario=ScenarioId.HEALTHY, seed=seed, duration_s=24 * 3600)
        self.telemetry_config = TelemetryConfig(window_size=8640)
        self.stream = TelemetryStream(self.episode, self.telemetry_config)
        self.engine = RiskEngine(bundle)
        self.speed = speed
        self.paused = False
        self.pause_reason: str | None = None
        self.assessment: RiskAssessment | None = None
        self.risk_history: list[dict] = []
        self.comparisons: dict[str, FutureComparison] = {}
        self.verifications: dict[str, VerificationResult] = {}
        self.agent_runs: dict[str, AgentTrace] = {}
        self.busy: str | None = None
        self._agent_task: asyncio.Task | None = None
        self.fault_injected = False
        self._alert_armed = True
        self._alert_pending: float | None = None
        self._subscribers: set[asyncio.Queue] = set()
        self._next_assess_t = ASSESS_EVERY_SIM_S
        self._task: asyncio.Task | None = None
        self._events_sent = 0
        # Warm up 30 simulated minutes so the models have a full window from the start.
        self.stream.advance(1800)
        self._assess_backlog()

    # ------------------------------------------------------------------ lifecycle
    def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name=f"session-{self.id}")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    def touch(self) -> None:
        self.last_active = time.monotonic()

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(TICK_WALL_S)
            if self.paused or self.busy:
                continue
            try:
                self._tick(self.speed * TICK_WALL_S)
            except Exception:
                log.exception("session tick failed", extra={"session_id": self.id})
                self.paused, self.pause_reason = True, "internal error during simulation step"
                self._broadcast({"type": "status", "data": self.status()})

    def _tick(self, sim_seconds: float) -> None:
        samples = self.stream.advance(sim_seconds)
        assessed = self._assess_backlog()
        if self.stream.twin.state.failed and not self.paused:
            self.paused, self.pause_reason = True, "simulated failure occurred"
        elif self._alert_pending is not None and not self.paused:
            self.paused = True
            self.pause_reason = (
                f"risk alert: P(fail within 60 min) reached {self._alert_pending:.0%}"
                " - review before continuing"
            )
        self._alert_pending = None
        self._broadcast(
            {
                "type": "tick",
                "data": {
                    "samples": [compact_sample(s) for s in samples],
                    "assessment": self.assessment.model_dump()
                    if assessed and self.assessment
                    else None,
                    "risk_point": self.risk_history[-1] if assessed and self.risk_history else None,
                    "events": [e.model_dump() for e in self._new_events()],
                    "status": self.status(),
                },
            }
        )

    def _assess_backlog(self) -> bool:
        assessed = False
        while self.stream.t_s >= self._next_assess_t:
            self._next_assess_t += ASSESS_EVERY_SIM_S
            window = list(self.stream.window)[-360:]
            if not window:
                continue
            self.assessment = self.engine.assess(window)
            assessed = True
            a = self.assessment
            point: dict[str, Any] = {"t": a.t_s, "available": a.available}
            if a.available:
                point.update(
                    {f"risk{h.horizon_min}": round(h.probability, 4) for h in a.horizons}
                    | {
                        "anomaly": round(a.anomaly.score, 4) if a.anomaly else None,
                        "anomalous": bool(a.anomaly and a.anomaly.is_anomalous),
                        "diagnosis": a.diagnosis[0].label if a.diagnosis else None,
                    }
                )
                risk60 = point.get("risk60")
                if risk60 is not None:
                    if self._alert_armed and risk60 >= ALERT_PAUSE_RISK:
                        self._alert_armed = False
                        self._alert_pending = risk60
                    elif risk60 < ALERT_REARM_RISK:
                        self._alert_armed = True
            self.risk_history.append(point)
        return assessed

    def _new_events(self):
        new = self.stream.events[self._events_sent :]
        self._events_sent = len(self.stream.events)
        return new

    # ------------------------------------------------------------------ pub/sub
    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=200)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.discard(q)

    def _broadcast(self, message: dict) -> None:
        for q in list(self._subscribers):
            if q.full():
                with contextlib.suppress(asyncio.QueueEmpty):
                    q.get_nowait()  # drop oldest; clients resync from the snapshot endpoint
            q.put_nowait(message)

    # ------------------------------------------------------------------ views
    def actuators(self) -> ActuatorSettings:
        s = self.stream.twin.state
        return ActuatorSettings(
            load_multiplier=s.load_multiplier,
            speed_setpoint=s.speed_setpoint,
            aux_boost=s.aux_boost,
        )

    def ground_truth(self) -> dict:
        s = self.stream.twin.state
        return {
            "label": "Simulator internals - hidden from the predictive models and the agent",
            "bearing_health": round(s.bearing_health, 4),
            "cooling_efficiency": round(s.cooling_efficiency, 4),
            "failed": s.failed,
            "failure_mode": s.failure_mode,
            "operating_hours": round(s.operating_s / 3600.0, 3),
            "in_maintenance": s.maintenance_until_s is not None,
            "shutdown": s.shutdown,
            "fault": self.stream.twin.config.fault.model_dump(),
        }

    def status(self) -> dict:
        s = self.stream.twin.state
        info = SCENARIOS[self.scenario]
        return {
            "session_id": self.id,
            "scenario": self.scenario.value,
            "scenario_title": info.title,
            "seed": self.seed,
            "sim_time_s": s.t_s,
            "speed": self.speed,
            "paused": self.paused,
            "pause_reason": self.pause_reason,
            "busy": self.busy,
            "running": s.running,
            "failed": s.failed,
            "failure_mode": s.failure_mode,
            "fault_injected": self.fault_injected,
            "actuators": self.actuators().model_dump(),
            "ground_truth": self.ground_truth(),
            "model_version": self.engine.bundle.version,
        }

    def snapshot(self) -> dict:
        samples = list(self.stream.window)
        return {
            "status": self.status(),
            "scenario": SCENARIOS[self.scenario].model_dump(),
            "samples": [compact_sample(s) for s in samples],
            "risk_history": self.risk_history,
            "assessment": self.assessment.model_dump() if self.assessment else None,
            "events": [e.model_dump() for e in self.stream.events],
            "comparisons": [c.id for c in self.comparisons.values()],
            "agent_runs": [
                {
                    "run_id": r.run_id,
                    "status": r.status,
                    "stage": r.stage,
                    "started_at": r.started_at,
                }
                for r in self.agent_runs.values()
            ],
        }

    # ------------------------------------------------------------------ controls
    def control(
        self, action: Literal["pause", "resume", "set_speed"], speed: float | None = None
    ) -> dict:
        if action == "pause":
            self.paused, self.pause_reason = True, "paused by user"
        elif action == "resume":
            if self.stream.twin.state.failed:
                raise SessionError("Machine has failed; start a new session to continue")
            self.paused, self.pause_reason = False, None
        elif action == "set_speed":
            if speed is None or not 1 <= speed <= 600:
                raise SessionError("speed must be between 1 and 600 simulated seconds per second")
            self.speed = speed
        status = self.status()
        self._broadcast({"type": "status", "data": status})
        return status

    def inject_fault(self) -> dict:
        if self.scenario is ScenarioId.HEALTHY:
            raise SessionError("The healthy scenario has no fault to inject")
        if self.fault_injected:
            raise SessionError("Fault already injected in this session")
        canonical = canonical_episode(self.scenario).fault
        now = self.stream.t_s
        update = canonical.model_dump(exclude_none=True)
        for key in ("cooling_fouling_onset_s", "bearing_defect_onset_s", "overload_onset_s"):
            if key in update:
                update[key] = now
        event = self.stream.inject_fault(
            update, source="user", label=SCENARIOS[self.scenario].title.lower()
        )
        self.fault_injected = True
        self._broadcast(
            {
                "type": "tick",
                "data": {
                    "samples": [],
                    "events": [e.model_dump() for e in self._new_events()],
                    "status": self.status(),
                },
            }
        )
        return event.model_dump()

    # ------------------------------------------------------------------ analysis
    def _require_assessment(self) -> RiskAssessment:
        if self.assessment is None:
            raise SessionError("No risk assessment yet")
        return self.assessment

    def estimate(self) -> StateEstimate:
        try:
            return estimate_state(list(self.stream.window)[-360:], self.actuators())
        except ValueError as exc:
            raise SessionError(str(exc)) from exc

    async def run_futures(
        self, actions: list[Action], horizon_min: float, n_members: int, state_source: str
    ) -> FutureComparison:
        if self.busy:
            raise SessionError(f"Session busy: {self.busy}")
        self.busy = "simulating futures"
        self._broadcast({"type": "status", "data": self.status()})
        try:
            kwargs: dict[str, Any] = {
                "horizon_min": horizon_min,
                "n_members": n_members,
                "base_seed": len(self.comparisons),
            }
            if state_source == "oracle":
                kwargs |= {"state_source": "oracle", "oracle_twin": self.stream.twin.clone()}
            else:
                kwargs |= {"state_source": "estimated", "estimate": self.estimate()}
            comp = await asyncio.to_thread(compare_futures, actions, **kwargs)
        finally:
            self.busy = None
            self._broadcast({"type": "status", "data": self.status()})
        self.comparisons[comp.id] = comp
        return comp

    async def _verify(
        self, proposal: Proposal, comp: FutureComparison | None
    ) -> VerificationResult:
        oracle = (
            self.stream.twin.clone() if comp is not None and comp.state_source == "oracle" else None
        )
        return await asyncio.to_thread(
            verify_independently,
            proposal,
            comp,
            self.assessment,
            now_s=self.stream.t_s,
            oracle_twin=oracle,
        )

    async def verify_action(
        self, action: Action, comparison_id: str | None, claimed_mode: str = "unknown"
    ) -> tuple[VerificationResult, str]:
        comp = self.comparisons.get(comparison_id) if comparison_id else None
        if comparison_id and comp is None:
            raise SessionError(f"Unknown comparison {comparison_id}")
        if comp is None:
            comp = next(
                (
                    c
                    for c in reversed(list(self.comparisons.values()))
                    if c.branch_for_action(action)
                ),
                None,
            )
        result = await self._verify(
            Proposal(action=action, claimed_failure_mode=claimed_mode, source="user"),  # type: ignore[arg-type]
            comp,
        )
        vid = f"v-{uuid.uuid4().hex[:8]}"
        self.verifications[vid] = result
        return result, vid

    async def run_agent(self, llm: MetaModelClient | None) -> AgentTrace:
        if self.busy:
            raise SessionError(f"Session busy: {self.busy}")
        assessment = self._require_assessment()
        snapshot = AgentSnapshot(
            session_id=self.id,
            t_s=self.stream.t_s,
            samples=list(self.stream.window)[-720:],
            actuators=self.actuators(),
            assessment=assessment,
        )

        def on_update(trace: AgentTrace) -> None:
            self.agent_runs[trace.run_id] = trace
            self._broadcast(
                {
                    "type": "agent",
                    "data": {
                        "run_id": trace.run_id,
                        "stage": trace.stage,
                        "status": trace.status,
                        "steps": len(trace.steps),
                    },
                }
            )

        orchestrator = AgentOrchestrator(snapshot, self.settings, llm=llm, on_update=on_update)
        self.agent_runs[orchestrator.trace.run_id] = orchestrator.trace
        self.busy = "agent reasoning (simulation clock paused)"
        self._broadcast({"type": "status", "data": self.status()})

        async def _go() -> None:
            try:
                trace = await orchestrator.run()
                # Keep the comparisons the agent produced so recommendations can be applied.
                for cid, comp in orchestrator.tools.comparisons.items():
                    self.comparisons[cid] = comp
                self.agent_runs[trace.run_id] = trace
            finally:
                self.busy = None
                self._broadcast({"type": "status", "data": self.status()})

        self._agent_task = asyncio.create_task(_go())
        return orchestrator.trace

    # ------------------------------------------------------------------ interventions
    async def apply_intervention(
        self,
        action: Action,
        approved: bool,
        source: Literal["user", "agent"],
        comparison_id: str | None,
    ) -> dict:
        if self.busy:
            raise SessionError(f"Session busy: {self.busy}")
        if self.stream.twin.state.failed:
            raise SessionError("Machine has failed; interventions are no longer possible")
        consequential = not isinstance(action, ContinueOperation)
        if consequential and not approved:
            raise SessionError(
                "Consequential interventions require explicit human approval (approved=true)"
            )
        verification = None
        if source == "agent" and not comparison_id:
            raise SessionError(
                "Agent recommendations must reference the comparison they were verified on"
            )
        if comparison_id:
            comp = self.comparisons.get(comparison_id)
            if comp is None:
                raise SessionError(f"Unknown comparison {comparison_id}")
            verification = await self._verify(Proposal(action=action, source=source), comp)
            if verification.verdict == "rejected":
                raise SessionError(
                    "Re-verification failed: " + "; ".join(verification.rejection_reasons)
                )
        event = self.stream.apply_action(action, source=source)
        event.payload["approved_by_human"] = approved
        event.payload["verified"] = verification is not None
        if verification is None and consequential:
            event.payload["note"] = "Operator command - not verified by the safety verifier"
        self._broadcast(
            {
                "type": "tick",
                "data": {
                    "samples": [],
                    "events": [e.model_dump() for e in self._new_events()],
                    "status": self.status(),
                },
            }
        )
        return {
            "event": event.model_dump(),
            "verification": verification.model_dump() if verification else None,
        }

    def replay_check(self) -> dict:
        """Re-run the session from its seed and intervention log; compare fingerprints."""
        start = time.perf_counter()
        replayed = replay(
            self.episode,
            self.telemetry_config,
            self.stream.intervention_log,
            until_s=self.stream.t_s,
        )
        live_fp, replay_fp = self.stream.fingerprint(), replayed.fingerprint()
        return {
            "deterministic": live_fp == replay_fp,
            "live_fingerprint": live_fp,
            "replay_fingerprint": replay_fp,
            "sim_time_s": self.stream.t_s,
            "interventions_replayed": len(self.stream.intervention_log),
            "compute_ms": round((time.perf_counter() - start) * 1000, 1),
        }


class SessionManager:
    def __init__(self, bundle: RiskBundle, settings: Settings) -> None:
        self.bundle = bundle
        self.settings = settings
        self.sessions: dict[str, LiveSession] = {}

    async def create(self, scenario: ScenarioId, seed: int, speed: float | None) -> LiveSession:
        await self.cleanup()
        if len(self.sessions) >= MAX_SESSIONS:
            raise SessionError("Too many active sessions; delete one first")
        session = await asyncio.to_thread(
            LiveSession,
            scenario,
            seed,
            self.bundle,
            self.settings,
            speed or self.settings.default_sim_speed,
        )
        session.start()
        self.sessions[session.id] = session
        log.info("session created", extra={"session_id": session.id})
        return session

    def get(self, session_id: str) -> LiveSession:
        session = self.sessions.get(session_id)
        if session is None:
            raise KeyError(session_id)
        session.touch()
        return session

    async def delete(self, session_id: str) -> None:
        session = self.sessions.pop(session_id, None)
        if session:
            await session.stop()

    async def cleanup(self) -> None:
        now = time.monotonic()
        for sid, s in list(self.sessions.items()):
            if now - s.last_active > SESSION_IDLE_TTL_S:
                await self.delete(sid)

    async def shutdown(self) -> None:
        for sid in list(self.sessions):
            await self.delete(sid)


def parse_action(payload: dict) -> Action:
    return ACTION_ADAPTER.validate_python(payload)
