"""Unit tests for the Safety Challenge adversarial verifier benchmark."""

from __future__ import annotations

import pytest

from foresight.branching import ActuatorSettings, estimate_state
from foresight.prediction import RiskEngine
from foresight.simulation import ScenarioId, canonical_episode
from foresight.telemetry import TelemetryStream
from foresight.verification.challenge import (
    SAFETY_CHALLENGES,
    execute_safety_challenge,
    list_safety_challenges,
)


def _actuators(stream: TelemetryStream) -> ActuatorSettings:
    s = stream.twin.state
    return ActuatorSettings(
        load_multiplier=s.load_multiplier,
        speed_setpoint=s.speed_setpoint,
        aux_boost=s.aux_boost,
    )


@pytest.fixture
def motor_cooling_state(small_bundle):
    stream = TelemetryStream(canonical_episode(ScenarioId.COOLING_DEGRADATION))
    engine = RiskEngine(small_bundle)
    for _ in range(60):
        stream.advance(60)
        assessment = engine.assess(list(stream.window))
    est = estimate_state(list(stream.window)[-360:], _actuators(stream))
    return stream, assessment, est


@pytest.fixture
def motor_bearing_state(small_bundle):
    stream = TelemetryStream(canonical_episode(ScenarioId.BEARING_DETERIORATION))
    engine = RiskEngine(small_bundle)
    for _ in range(60):
        stream.advance(60)
        assessment = engine.assess(list(stream.window))
    est = estimate_state(list(stream.window)[-360:], _actuators(stream))
    return stream, assessment, est


def test_list_safety_challenges():
    challenges = list_safety_challenges()
    assert len(challenges) == 4
    ids = {c.challenge_id for c in challenges}
    assert ids == {
        "bearing_derate_trap",
        "overload_thermal_breach",
        "delayed_inspection_past_failure",
        "hallucinated_evidence_actuation",
    }


def test_hallucinated_evidence_challenge_rejected(motor_cooling_state):
    stream, assessment, est = motor_cooling_state
    result = execute_safety_challenge(
        "hallucinated_evidence_actuation",
        session_id="test_sess_chal",
        t0_s=stream.t_s,
        estimate=est,
        assessment=assessment,
        oracle_twin=stream.twin,
    )

    assert result.verdict == "rejected"
    assert result.direct_actuation_blocked is True
    assert "evidence_exists" in [c.name for c in result.all_checks if c.status == "fail"]
    assert "DIRECT ACTUATION BLOCKED" in result.actuation_barrier_message


def test_delayed_inspection_challenge_rejected(motor_cooling_state):
    stream, assessment, est = motor_cooling_state
    result = execute_safety_challenge(
        "delayed_inspection_past_failure",
        session_id="test_sess_chal",
        t0_s=stream.t_s,
        estimate=est,
        assessment=assessment,
        oracle_twin=stream.twin,
    )

    assert result.verdict == "rejected"
    assert result.direct_actuation_blocked is True
    failed_names = [c.name for c in result.all_checks if c.status == "fail"]
    assert len(failed_names) > 0


def test_bearing_derate_trap_rejected(motor_bearing_state):
    stream, assessment, est = motor_bearing_state
    result = execute_safety_challenge(
        "bearing_derate_trap",
        session_id="test_sess_chal_bearing",
        t0_s=stream.t_s,
        estimate=est,
        assessment=assessment,
        oracle_twin=stream.twin,
    )

    assert result.verdict == "rejected"
    assert result.direct_actuation_blocked is True
    assert len(result.rejection_reasons) > 0
