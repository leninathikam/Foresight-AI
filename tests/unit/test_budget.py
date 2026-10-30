"""Tests for concurrency-safe atomic LLM budget reservations and fallback attribution."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

import foresight_api.main as main
from foresight.agents.budget import (
    BudgetExceededError,
    LLMBudgetManager,
    calculate_actual_cost,
)
from foresight.agents.llm import LLMResponse
from foresight.agents.orchestrator import AgentOrchestrator
from foresight.agents.tools import AgentSnapshot
from foresight.branching import ActuatorSettings
from foresight.config import ProviderConfig, get_settings
from foresight.prediction import RiskEngine


@pytest.fixture
def test_provider_config() -> ProviderConfig:
    return ProviderConfig(
        name="meta",
        label="Meta Model API",
        trace_id="meta-model-api",
        base_url="https://api.meta.ai/v1",
        api_key=None,
        model="muse-spark-1.3",
        price_input_per_m=1.25,
        price_cached_input_per_m=1.25,
        price_output_per_m=4.25,
        efforts=("minimal", "low", "medium", "high", "xhigh"),
    )


@pytest.fixture
def cooling_snapshot(small_bundle, cooling_stream_100min) -> AgentSnapshot:
    engine = RiskEngine(small_bundle)
    a = engine.assess(list(cooling_stream_100min.window))
    return AgentSnapshot(
        session_id="test",
        t_s=cooling_stream_100min.t_s,
        samples=list(cooling_stream_100min.window)[-720:],
        actuators=ActuatorSettings(),
        assessment=a,
    )


@pytest.mark.asyncio
async def test_atomic_reservation_and_reconciliation():
    mgr = LLMBudgetManager(total_budget_usd=1.00, session_budget_usd=0.50)

    # 1. Initial state
    summary = await mgr.get_summary("sess-1")
    assert summary.total_budget_usd == 1.00
    assert summary.total_spent_usd == 0.0
    assert summary.total_reserved_usd == 0.0
    assert summary.total_remaining_usd == 1.00
    assert summary.spending_ceiling_guaranteed is False
    assert "Client-side" in summary.disclaimer

    # 2. Reserve $0.05
    res = await mgr.reserve("sess-1", 0.05)
    assert res.estimated_usd == 0.05
    summary = await mgr.get_summary("sess-1")
    assert summary.total_reserved_usd == 0.05
    assert summary.session_reserved_usd == 0.05
    assert summary.total_remaining_usd == 0.95
    assert summary.session_remaining_usd == 0.45
    assert summary.active_reservations_count == 1

    # 3. Reconcile with actual lower cost $0.03
    await mgr.reconcile(res.reservation_id, actual_usd=0.03)
    summary = await mgr.get_summary("sess-1")
    assert summary.total_reserved_usd == 0.0
    assert summary.session_reserved_usd == 0.0
    assert summary.total_spent_usd == 0.03
    assert summary.session_spent_usd == 0.03
    assert summary.total_remaining_usd == 0.97
    assert summary.session_remaining_usd == 0.47
    assert summary.active_reservations_count == 0


@pytest.mark.asyncio
async def test_reservation_context_manager_releases_on_failure():
    mgr = LLMBudgetManager(total_budget_usd=1.00, session_budget_usd=0.50)

    # Simulate an operation that fails midway
    with pytest.raises(RuntimeError, match="Network timeout simulated"):
        async with mgr.reservation_context("sess-1", estimated_usd=0.08) as _:
            summary = await mgr.get_summary("sess-1")
            assert summary.total_reserved_usd == 0.08
            raise RuntimeError("Network timeout simulated")

    # After exception, reservation must be automatically released
    summary = await mgr.get_summary("sess-1")
    assert summary.total_reserved_usd == 0.0
    assert summary.session_reserved_usd == 0.0
    assert summary.total_spent_usd == 0.0
    assert summary.active_reservations_count == 0


@pytest.mark.asyncio
async def test_concurrent_reservations_cannot_bypass_budget():
    # Budget allows exactly 3 requests of $0.03 (total $0.10)
    mgr = LLMBudgetManager(total_budget_usd=0.10, session_budget_usd=0.10)

    succeeded = 0
    rejected = 0

    async def worker(idx: int):
        nonlocal succeeded, rejected
        try:
            res = await mgr.reserve("sess-concurrent", estimated_usd=0.03)
            # Hold reservation briefly
            await asyncio.sleep(0.01)
            await mgr.reconcile(res.reservation_id, actual_usd=0.03)
            succeeded += 1
        except BudgetExceededError:
            rejected += 1

    # Launch 10 concurrent requests at the same instant
    await asyncio.gather(*(worker(i) for i in range(10)))

    # Exactly 3 should succeed, 7 rejected
    assert succeeded == 3
    assert rejected == 7
    summary = await mgr.get_summary("sess-concurrent")
    assert summary.total_spent_usd == pytest.approx(0.09, abs=1e-5)
    assert summary.total_reserved_usd == 0.0


@pytest.mark.asyncio
async def test_per_session_budget_isolation():
    mgr = LLMBudgetManager(total_budget_usd=10.00, session_budget_usd=0.04)

    # Session 1 spends up to its limit
    res1 = await mgr.reserve("sess-A", 0.03)
    await mgr.reconcile(res1.reservation_id, 0.03)

    # Next attempt for Session A exceeding $0.04 must be rejected
    with pytest.raises(BudgetExceededError, match="Session 'sess-A' budget exceeded"):
        await mgr.reserve("sess-A", 0.02)

    # But Session B should still have its own full quota
    res2 = await mgr.reserve("sess-B", 0.03)
    await mgr.reconcile(res2.reservation_id, 0.03)
    summary_b = await mgr.get_summary("sess-B")
    assert summary_b.session_spent_usd == 0.03


def test_conservative_accounting_when_usage_missing(test_provider_config):
    # Case 1: Normal reported tokens
    normal_resp = LLMResponse(
        id="resp-1",
        model="muse-spark-1.3",
        function_calls=[],
        status="completed",
        output_text="Test answer",
        latency_ms=50.0,
        input_tokens=1000,
        cached_input_tokens=0,
        output_tokens=500,
    )
    cost = calculate_actual_cost(test_provider_config, normal_resp, prompt_input="abc")
    # 1000/1M * 1.25 + 500/1M * 4.25 = 0.00125 + 0.002125 = 0.003375
    assert cost == pytest.approx(0.003375, abs=1e-5)

    # Case 2: Provider returns 0 tokens
    missing_resp = LLMResponse(
        id="resp-2",
        model="muse-spark-1.3",
        function_calls=[],
        status="completed",
        output_text="A" * 600,  # ~200 tokens
        latency_ms=50.0,
        input_tokens=0,
        cached_input_tokens=0,
        output_tokens=0,
    )
    # Conservative accounting must floor input tokens and calculate output from text
    cost_conservative = calculate_actual_cost(
        test_provider_config, missing_resp, prompt_input="P" * 1500
    )
    assert cost_conservative > 0
    # Input >= 500 tokens, output >= 200 tokens
    assert cost_conservative > 0.001


@pytest.mark.asyncio
async def test_agent_deterministic_fallback_when_budget_exceeded(cooling_snapshot):
    settings = get_settings()

    # Mock LLM client
    mock_llm = MagicMock()
    mock_llm.provider = "meta-model-api"
    mock_llm.model = "muse-spark-1.3"
    mock_llm.reasoning_effort = "medium"
    mock_llm.config = ProviderConfig(
        name="meta",
        label="Meta Model API",
        trace_id="meta-model-api",
        base_url="https://api.meta.ai/v1",
        api_key=None,
        model="muse-spark-1.3",
        price_input_per_m=1.25,
        price_cached_input_per_m=1.25,
        price_output_per_m=4.25,
        efforts=("minimal", "low", "medium", "high", "xhigh"),
    )

    # Budget manager with $0.00 limit (budget already exceeded)
    budget_mgr = LLMBudgetManager(total_budget_usd=0.00, session_budget_usd=0.00)

    orchestrator = AgentOrchestrator(
        snapshot=cooling_snapshot,
        settings=settings,
        llm=mock_llm,
        budget_manager=budget_mgr,
    )

    trace = await orchestrator.run()

    # The agent run must succeed via fallback
    assert trace.status == "completed"
    assert trace.fallback_reason == "budget_exceeded"
    assert "deterministic-planner fallback (budget exceeded)" in trace.provider
    assert "LLM budget limit reached" in (trace.notice or "")
    assert trace.recommendation is not None
    assert trace.recommendation.selected_by in ("optimizer_fallback", "deterministic_planner")
    assert trace.recommendation.rationale_source == "deterministic"


def test_budget_api_endpoints(monkeypatch, small_bundle):
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.setenv("MODEL_API_KEY", "")
    get_settings.cache_clear()
    monkeypatch.setattr(main, "load_or_train_bundle", lambda: small_bundle)

    with TestClient(main.app) as client:
        # 1. Global budget endpoint is public
        r = client.get("/api/budget")
        assert r.status_code == 200
        data = r.json()
        assert "total_spent_usd" in data
        assert "spending_ceiling_guaranteed" in data
        assert data["spending_ceiling_guaranteed"] is False
        assert "disclaimer" in data

        # 2. Session budget requires ownership token
        r_create = client.post("/api/sessions", json={"scenario": "healthy", "seed": 42})
        assert r_create.status_code == 200
        snap = r_create.json()
        sid = snap["status"]["session_id"]
        token = snap["owner_token"]

        # Request without token fails 403
        client.cookies.clear()
        r_unauth = client.get(f"/api/sessions/{sid}/budget")
        assert r_unauth.status_code == 403

        # Request with header token succeeds 200
        r_auth = client.get(f"/api/sessions/{sid}/budget", headers={"X-Session-Token": token})
        assert r_auth.status_code == 200
        s_data = r_auth.json()
        assert s_data["session_spent_usd"] == 0.0
        assert s_data["spending_ceiling_guaranteed"] is False
