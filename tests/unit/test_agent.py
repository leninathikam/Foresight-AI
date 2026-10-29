"""Agent workflow tests.

The LLM path is exercised against a *scripted* mock of the Responses API (test-only; it is not
Meta inference). It checks the protocol handling: structured hypotheses, tool calls, verifier
rejection, and revision.
"""

from __future__ import annotations

import json

import httpx
import pytest

from foresight.agents import AgentOrchestrator, AgentSnapshot, AgentStage, MetaModelClient
from foresight.branching import ActuatorSettings
from foresight.config import Settings
from foresight.prediction import RiskEngine
from foresight.simulation import ScenarioId, canonical_episode
from foresight.telemetry import TelemetryStream


@pytest.fixture(scope="module")
def cooling_snapshot(request):
    bundle = request.getfixturevalue("small_bundle")
    stream = TelemetryStream(canonical_episode(ScenarioId.COOLING_DEGRADATION))
    engine = RiskEngine(bundle)
    for _ in range(100):
        stream.advance(60)
        a = engine.assess(list(stream.window))
    return AgentSnapshot("test", stream.t_s, list(stream.window)[-720:], ActuatorSettings(), a)


def _msg(text: str, rid: str) -> dict:
    return {
        "id": rid,
        "status": "completed",
        "output": [{"type": "message", "content": [{"type": "output_text", "text": text}]}],
        "usage": {"input_tokens": 100, "output_tokens": 50},
    }


def _call(name: str, args: dict, rid: str, call_id: str) -> dict:
    return {
        "id": rid,
        "status": "completed",
        "output": [
            {
                "type": "function_call",
                "call_id": call_id,
                "name": name,
                "arguments": json.dumps(args),
            }
        ],
        "usage": {"input_tokens": 100, "output_tokens": 20},
    }


HYPOTHESES = {
    "summary": "Winding temperature is rising faster than the datasheet model predicts.",
    "hypotheses": [
        {
            "failure_mode": "thermal",
            "statement": "Cooling degradation",
            "likelihood": "high",
            "supporting_evidence_ids": ["obs:rise_residual_k", "obs:not_a_real_id"],
            "would_be_refuted_by": "residual returning to 0",
        }
    ],
    "candidate_interventions": [
        {"type": "reduce_speed", "fraction": 0.3, "boost": None, "delay_minutes": None},
        {"type": "schedule_inspection", "fraction": None, "boost": None, "delay_minutes": 10},
    ],
    "information_needed": [],
}


def scripted_transport(requests: list[dict]) -> httpx.MockTransport:
    script = [
        _msg(json.dumps(HYPOTHESES), "r1"),
        _call(
            "compare_futures",
            {
                "actions": [
                    {"type": "reduce_speed", "fraction": 0.3},
                    {"type": "schedule_inspection", "delay_minutes": 10},
                ]
            },
            "r2",
            "c1",
        ),
        _call(
            "submit_recommendation",
            {
                "action": {"type": "reduce_speed", "fraction": 0.3},
                "claimed_failure_mode": "thermal",
                "cited_evidence_ids": ["obs:rise_residual_k"],
                "rationale": "Slow down to reduce heat.",
            },
            "r3",
            "c2",
        ),
        _call(
            "submit_recommendation",
            {
                "action": {"type": "schedule_inspection", "delay_minutes": 10},
                "claimed_failure_mode": "thermal",
                "cited_evidence_ids": ["obs:rise_residual_k", "ml:risk_60m"],
                "rationale": "Inspection restores cooling before the limit is reached.",
            },
            "r4",
            "c3",
        ),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return httpx.Response(200, json=script[len(requests) - 1])

    return httpx.MockTransport(handler)


async def test_agent_revises_after_verifier_rejection(cooling_snapshot):
    sent: list[dict] = []
    settings = Settings(MODEL_API_KEY="test")
    llm = MetaModelClient(settings, transport=scripted_transport(sent))
    trace = await AgentOrchestrator(cooling_snapshot, settings, llm=llm).run()

    assert trace.status == "completed", trace.error
    assert trace.stage == AgentStage.DONE
    assert trace.stage_history[:3] == [
        AgentStage.OBSERVE,
        AgentStage.ANALYZE,
        AgentStage.HYPOTHESIZE,
    ]
    assert AgentStage.SIMULATE in trace.stage_history and AgentStage.VERIFY in trace.stage_history
    # first proposal (reduce speed) rejected by the deterministic verifier
    assert len(trace.rejected) == 1 and trace.rejected[0].action["type"] == "reduce_speed"
    rec = trace.recommendation
    assert rec.status == "awaiting_approval" and rec.action["type"] == "schedule_inspection"
    assert rec.selected_by == "agent" and rec.rationale_source == "llm"
    assert rec.verification.verdict != "rejected"
    # hallucinated evidence id in a hypothesis is detected and counted
    assert trace.usage.hallucinated_evidence_ids == 1
    assert trace.usage.llm_calls == 4
    # protocol: structured output on the first call, tool results answered via previous_response_id
    assert sent[0]["text"]["format"]["type"] == "json_schema"
    assert sent[2]["previous_response_id"] == "r2"
    assert (
        sent[2]["input"][0]["type"] == "function_call_output"
        and sent[2]["input"][0]["call_id"] == "c1"
    )
    assert "failed_checks" in sent[3]["input"][0]["output"]


async def test_agent_falls_back_when_provider_fails(cooling_snapshot):
    def handler(request):
        return httpx.Response(503, json={"error": {"message": "unavailable"}})

    settings = Settings(MODEL_API_KEY="test", FORESIGHT_LLM_MAX_RETRIES=0)
    llm = MetaModelClient(settings, transport=httpx.MockTransport(handler))
    trace = await AgentOrchestrator(cooling_snapshot, settings, llm=llm).run()
    assert trace.status == "completed"
    assert "fallback" in trace.provider and trace.notice
    assert trace.recommendation.selected_by == "optimizer_fallback"
    assert trace.recommendation.action["type"] == "schedule_inspection"


async def test_deterministic_planner_without_key(cooling_snapshot):
    trace = await AgentOrchestrator(cooling_snapshot, Settings(MODEL_API_KEY=None)).run()
    assert trace.status == "completed"
    assert trace.provider == "deterministic-planner" and "not from a Meta model" in trace.notice
    assert trace.hypotheses[0].source == "deterministic"
    assert trace.recommendation.rationale_source == "deterministic"
    assert set(trace.report) == {
        "observed_evidence",
        "ml_predictions",
        "simulation_estimates",
        "hypotheses",
        "verified_results",
        "information_value",
        "recommendation",
    }
    # Real fouling is a well-supported trend, so the information gate lets the action through.
    rec = trace.recommendation
    assert rec.status == "awaiting_approval"
    assert rec.information is not None and rec.information.decision == "act_now"
    assert any(s.name == "assess_information_value" for s in trace.steps)


async def test_gate_holds_back_verified_action_when_evidence_is_weak(cooling_snapshot, monkeypatch):
    from foresight.agents import tools
    from foresight.verification import InformationAssessment

    held = InformationAssessment(
        decision="gather_information",
        defer_minutes=15.0,
        trends=[],
        unsupported_trends=["cooling_fouling"],
        reasons=["test"],
        summary="Gather 15 more minutes of telemetry before acting.",
    )
    monkeypatch.setattr(tools, "assess_information_value", lambda *a, **k: held)
    trace = await AgentOrchestrator(cooling_snapshot, Settings(MODEL_API_KEY=None)).run()
    rec = trace.recommendation
    assert rec.status == "gather_information"
    assert rec.action is not None and rec.verification.verdict != "rejected"
    assert rec.rationale.startswith("Gather 15 more minutes")


async def test_gate_can_be_disabled(cooling_snapshot, monkeypatch):
    from dataclasses import replace

    from foresight.agents import tools

    def boom(*a, **k):
        raise AssertionError("gate must not run")

    monkeypatch.setattr(tools, "assess_information_value", boom)
    snap = replace(cooling_snapshot, information_gathering=False)
    trace = await AgentOrchestrator(snap, Settings(MODEL_API_KEY=None)).run()
    assert trace.recommendation.status == "awaiting_approval"
    assert trace.recommendation.information is None
