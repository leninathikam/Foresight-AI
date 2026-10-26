from __future__ import annotations

import itertools
import math

from foresight.simulation import ReduceLoad, ScenarioId, canonical_episode
from foresight.telemetry import (
    VALID_RANGES,
    TelemetryConfig,
    TelemetryStream,
    replay,
    validate_values,
)


def test_validation_marks_missing_and_out_of_range():
    values, quality = validate_values(
        {
            "temperature_c": float("nan"),
            "ambient_c": 25.0,
            "vibration_mm_s": 999.0,
            "speed_rpm": 1470.0,
            "load_pct": 80.0,
            "current_a": 20.0,
            "voltage_v": 400.0,
        }
    )
    assert values["temperature_c"] is None and quality["temperature_c"] == "missing"
    assert values["vibration_mm_s"] is None and quality["vibration_mm_s"] == "out_of_range"
    assert quality["speed_rpm"] == "ok"


def test_sampling_rate_and_sim_time():
    stream = TelemetryStream(
        canonical_episode(ScenarioId.HEALTHY), TelemetryConfig(sample_interval_s=20)
    )
    samples = stream.advance(600)
    assert len(samples) == 30
    assert math.isclose(samples[-1].t_s, 600)
    assert all(b.t_s - a.t_s == 20 for a, b in itertools.pairwise(samples))


def test_dropouts_are_injected_and_never_out_of_physical_range():
    cfg = TelemetryConfig(dropout_probability=0.2, spike_probability=0.05)
    stream = TelemetryStream(canonical_episode(ScenarioId.HEALTHY), cfg)
    samples = stream.advance(3600)
    missing = sum(v is None for s in samples for v in s.values.values())
    assert missing > 0
    for s in samples:
        for name, v in s.values.items():
            lo, hi = VALID_RANGES[name]
            assert v is None or lo <= v <= hi


def test_rolling_window_is_bounded():
    stream = TelemetryStream(canonical_episode(ScenarioId.HEALTHY), TelemetryConfig(window_size=50))
    stream.advance(3600)
    assert len(stream.window) == 50


def test_replay_reproduces_session_with_interventions_and_faults():
    episode = canonical_episode(ScenarioId.HEALTHY)
    cfg = TelemetryConfig()
    live = TelemetryStream(episode, cfg)
    live.advance(900)
    live.inject_fault(
        {"overload_onset_s": live.t_s, "overload_target_load": 1.4, "overload_ramp_h": 1.0}
    )
    live.advance(1800)
    live.apply_action(ReduceLoad(fraction=0.25))
    live.advance(1200)
    rerun = replay(episode, cfg, live.intervention_log, until_s=live.t_s)
    assert rerun.fingerprint() == live.fingerprint()
    assert [e.kind for e in live.events] == [e.kind for e in rerun.events]


def test_events_record_interventions():
    stream = TelemetryStream(canonical_episode(ScenarioId.HEALTHY))
    stream.advance(60)
    event = stream.apply_action(ReduceLoad(fraction=0.1))
    assert event.kind == "intervention" and event.t_s == 60
    assert stream.intervention_log[-1].action["type"] == "reduce_load"
