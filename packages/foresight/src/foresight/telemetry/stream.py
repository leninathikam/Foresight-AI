"""Telemetry acquisition on top of the digital twin.

Responsibilities:
* sample the twin at a configurable rate (simulation time, independent of wall-clock time),
* inject realistic data-quality problems (dropouts, spikes) from a dedicated RNG stream,
* validate readings against physical ranges and mark invalid values as missing,
* keep a bounded rolling window and an append-only intervention/event log,
* allow exact deterministic replay from (episode config, telemetry config, action log).
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import deque
from dataclasses import asdict
from typing import Literal

import numpy as np
from pydantic import BaseModel, Field, TypeAdapter

from foresight.simulation import STEP_S, Action, EpisodeConfig, MotorTwin, describe_action
from foresight.simulation.twin import GroundTruth, SensorReading

CHANNELS: tuple[str, ...] = (
    "temperature_c",
    "ambient_c",
    "vibration_mm_s",
    "speed_rpm",
    "load_pct",
    "current_a",
    "voltage_v",
)

# Physically plausible ranges. Values outside are treated as sensor faults, never clipped.
VALID_RANGES: dict[str, tuple[float, float]] = {
    "temperature_c": (-40.0, 250.0),
    "ambient_c": (-40.0, 70.0),
    "vibration_mm_s": (0.0, 50.0),
    "speed_rpm": (0.0, 2000.0),
    "load_pct": (0.0, 250.0),
    "current_a": (0.0, 120.0),
    "voltage_v": (0.0, 500.0),
}

_ACTION_ADAPTER: TypeAdapter[Action] = TypeAdapter(Action)


class TelemetryConfig(BaseModel):
    sample_interval_s: float = Field(10.0, ge=STEP_S)
    dropout_probability: float = Field(0.01, ge=0.0, le=0.5)
    spike_probability: float = Field(0.002, ge=0.0, le=0.1)
    window_size: int = Field(720, ge=10, description="Samples kept in the rolling window")


class TelemetrySample(BaseModel):
    seq: int
    t_s: float
    values: dict[str, float | None]
    quality: dict[str, Literal["ok", "missing", "out_of_range"]]
    running: bool


class TelemetryEvent(BaseModel):
    seq: int
    t_s: float
    kind: Literal["intervention", "fault_injected", "failure", "maintenance", "note"]
    summary: str
    payload: dict = Field(default_factory=dict)
    source: Literal["user", "agent", "system", "replay"] = "system"


class InterventionLogEntry(BaseModel):
    """Everything needed to replay an intervention at the exact simulation time it happened."""

    t_s: float
    action: dict
    source: Literal["user", "agent", "system", "replay"] = "user"


def validate_values(raw: dict[str, float]) -> tuple[dict[str, float | None], dict[str, str]]:
    values: dict[str, float | None] = {}
    quality: dict[str, str] = {}
    for name in CHANNELS:
        value = raw.get(name)
        if value is None or not math.isfinite(value):
            values[name], quality[name] = None, "missing"
            continue
        lo, hi = VALID_RANGES[name]
        if lo <= value <= hi:
            values[name], quality[name] = float(value), "ok"
        else:
            values[name], quality[name] = None, "out_of_range"
    return values, quality


class TelemetryStream:
    def __init__(self, episode: EpisodeConfig, config: TelemetryConfig | None = None) -> None:
        self.episode = episode
        self.config = config or TelemetryConfig()
        self.twin = MotorTwin(episode)
        quality_seed = np.random.SeedSequence([episode.seed, 0x7E1E])
        self._quality_rng = np.random.Generator(np.random.PCG64(quality_seed))
        self.window: deque[TelemetrySample] = deque(maxlen=self.config.window_size)
        self.truth_window: deque[GroundTruth] = deque(maxlen=self.config.window_size)
        self.events: list[TelemetryEvent] = []
        self.intervention_log: list[InterventionLogEntry] = []
        self._seq = 0
        self._event_seq = 0
        self._steps_per_sample = max(1, round(self.config.sample_interval_s / STEP_S))
        self._step_count = 0
        self._failure_logged = False
        self._in_maintenance = False

    @property
    def t_s(self) -> float:
        return self.twin.state.t_s

    # ------------------------------------------------------------------ events
    def _log_event(self, kind, summary: str, payload: dict | None = None, source="system") -> None:
        self._event_seq += 1
        self.events.append(
            TelemetryEvent(
                seq=self._event_seq,
                t_s=self.t_s,
                kind=kind,
                summary=summary,
                payload=payload or {},
                source=source,
            )
        )

    def apply_action(self, action: Action, source: str = "user") -> TelemetryEvent:
        record = self.twin.apply_action(action)
        action_dict = _ACTION_ADAPTER.dump_python(action, mode="json")
        self.intervention_log.append(
            InterventionLogEntry(t_s=self.t_s, action=action_dict, source=source)
        )
        self._log_event(
            "intervention",
            describe_action(action),
            {"action": action_dict, "applied": record.applied},
            source=source,
        )
        return self.events[-1]

    def inject_fault(self, fault_update: dict, source: str = "user") -> TelemetryEvent:
        """Activate a fault *now*. Recorded in the log so replay reproduces it."""
        fault = self.twin.config.fault.model_copy(update=fault_update)
        self.twin.config = self.twin.config.model_copy(update={"fault": fault})
        self.intervention_log.append(
            InterventionLogEntry(
                t_s=self.t_s, action={"type": "inject_fault", **fault_update}, source=source
            )
        )
        self._log_event(
            "fault_injected", f"Fault injected: {', '.join(fault_update)}", fault_update, source
        )
        return self.events[-1]

    # ------------------------------------------------------------------ sampling
    def _make_sample(self, reading: SensorReading) -> TelemetrySample:
        raw = {name: getattr(reading, name) for name in CHANNELS}
        # Fixed-count draws keep the quality stream aligned regardless of values.
        dropout_draws = self._quality_rng.random(len(CHANNELS))
        spike_draws = self._quality_rng.random(len(CHANNELS))
        for i, name in enumerate(CHANNELS):
            if dropout_draws[i] < self.config.dropout_probability:
                raw[name] = float("nan")
            elif spike_draws[i] < self.config.spike_probability:
                raw[name] = raw[name] * 25.0 + 500.0  # gross sensor glitch
        values, quality = validate_values(raw)
        self._seq += 1
        return TelemetrySample(
            seq=self._seq, t_s=reading.t_s, values=values, quality=quality, running=reading.running
        )

    def advance(self, sim_seconds: float) -> list[TelemetrySample]:
        """Advance simulation time and return the samples produced."""
        produced: list[TelemetrySample] = []
        n_steps = max(0, round(sim_seconds / STEP_S))
        for _ in range(n_steps):
            reading, truth = self.twin.step()
            self._step_count += 1
            if truth.in_maintenance != self._in_maintenance:
                self._in_maintenance = truth.in_maintenance
                self._log_event(
                    "maintenance",
                    "Inspection started (machine stopped)"
                    if truth.in_maintenance
                    else "Inspection complete, restarted",
                    {"bearing_replacements": self.twin.state.bearing_replacements},
                )
            if truth.failed and not self._failure_logged:
                self._failure_logged = True
                self._log_event(
                    "failure",
                    f"Simulated {truth.failure_mode} failure",
                    {"mode": truth.failure_mode},
                )
            if self._step_count % self._steps_per_sample == 0:
                sample = self._make_sample(reading)
                self.window.append(sample)
                self.truth_window.append(truth)
                produced.append(sample)
        return produced

    # ------------------------------------------------------------------ replay
    def fingerprint(self) -> str:
        """Hash of the sample window + twin state; equal fingerprints mean identical runs."""
        payload = {
            "samples": [s.model_dump() for s in self.window],
            "state": asdict(self.twin.state),
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def replay(
    episode: EpisodeConfig,
    config: TelemetryConfig,
    log: list[InterventionLogEntry],
    until_s: float,
) -> TelemetryStream:
    """Re-run a session from scratch, re-applying logged interventions at their sim times."""
    stream = TelemetryStream(episode, config)
    for entry in sorted(log, key=lambda e: e.t_s):
        stream.advance(entry.t_s - stream.t_s)
        if entry.action.get("type") == "inject_fault":
            update = {k: v for k, v in entry.action.items() if k != "type"}
            stream.inject_fault(update, source="replay")
        else:
            stream.apply_action(_ACTION_ADAPTER.validate_python(entry.action), source="replay")
    stream.advance(until_s - stream.t_s)
    return stream
