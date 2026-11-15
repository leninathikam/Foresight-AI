"""Integration tests for Berkeley x DeepMind Hackathon endpoints:
- Future Arena 3-way simulation
- Safety Challenge adversarial gating
- Tamper-evident Decision Receipts
- Multimodal evidence analysis
- Documented live Gemini integration
"""

from __future__ import annotations

import base64
import os

import pytest
from fastapi.testclient import TestClient

from foresight.config import get_settings


@pytest.fixture
def api_client(monkeypatch, small_bundle):
    get_settings.cache_clear()
    import foresight_api.main as main

    monkeypatch.setattr(main, "load_or_train_bundle", lambda: small_bundle)
    with TestClient(main.app) as c:
        yield c
    get_settings.cache_clear()


def _advance(client: TestClient, sid: str, minutes: int) -> None:
    session = client.app.state.sessions.get(sid)
    for _ in range(minutes):
        session._tick(60)


def _init_active_session(client: TestClient, scenario: str = "cooling_degradation") -> str:
    snap = client.post("/api/sessions", json={"scenario": scenario, "seed": 42}).json()
    sid = snap["status"]["session_id"]
    client.post(f"/api/sessions/{sid}/control", json={"action": "pause"})
    client.post(f"/api/sessions/{sid}/inject")
    _advance(client, sid, 70)
    return sid


def test_future_arena_endpoint(api_client):
    sid = _init_active_session(api_client, "cooling_degradation")

    resp = api_client.post(
        f"/api/sessions/{sid}/arena",
        json={"horizon_min": 120.0, "members": 4, "reduce_load_fraction": 0.30},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["session_id"] == sid
    assert len(data["scenarios"]) == 3
    scenario_ids = [s["scenario_id"] for s in data["scenarios"]]
    assert scenario_ids == ["continue_operating", "reduce_load", "planned_maintenance"]
    assert data["winner_scenario_id"] in scenario_ids
    assert len(data["recommendation_reason"]) > 0

    # Ensure each scenario has bands and safety evaluation
    for sc in data["scenarios"]:
        assert sc["failure_incidence"] >= 0.0
        assert "p50" in sc["temperature_band"]
        assert sc["safety_status"] in ("accepted", "accepted_with_warnings", "rejected")


def test_safety_challenge_catalog_and_execution(api_client):
    cat_resp = api_client.get("/api/safety-challenge/catalog")
    assert cat_resp.status_code == 200
    catalog = cat_resp.json()
    assert len(catalog) == 4

    challenge_ids = [c["challenge_id"] for c in catalog]
    assert "hallucinated_evidence_actuation" in challenge_ids
    assert "bearing_derate_trap" in challenge_ids

    sid = _init_active_session(api_client, "bearing_deterioration")

    exec_resp = api_client.post(
        f"/api/sessions/{sid}/safety-challenge",
        json={"challenge_id": "hallucinated_evidence_actuation"},
    )
    assert exec_resp.status_code == 200, exec_resp.text
    res = exec_resp.json()

    assert res["challenge_id"] == "hallucinated_evidence_actuation"
    assert res["verdict"] == "rejected"
    assert res["direct_actuation_blocked"] is True
    assert "DIRECT ACTUATION BLOCKED" in res["actuation_barrier_message"]
    assert len(res["decision_hash"]) == 64


def test_decision_receipt_generation_and_verification(api_client):
    sid = _init_active_session(api_client, "cooling_degradation")

    # Generate a receipt
    resp = api_client.post(
        f"/api/sessions/{sid}/receipt",
        json={
            "action": {"type": "schedule_inspection", "delay_minutes": 15},
            "claimed_fault_mode": "cooling_degradation",
            "cited_evidence_ids": ["obs:temperature_c"],
            "human_approved": True,
            "operator_id": "OP-JUDGE-BERKELEY",
        },
    )
    assert resp.status_code == 200, resp.text
    receipt = resp.json()

    assert receipt["session_id"] == sid
    assert receipt["human_approval"]["status"] == "approved"
    assert receipt["human_approval"]["operator_id"] == "OP-JUDGE-BERKELEY"
    assert len(receipt["sha256_digest"]) == 64

    # Verify receipt integrity via verification endpoint
    verify_resp = api_client.post("/api/receipt/verify", json={"receipt": receipt})
    assert verify_resp.status_code == 200
    vdata = verify_resp.json()
    assert vdata["valid"] is True
    assert vdata["recorded_digest"] == vdata["computed_digest"]

    # Tamper with receipt and verify failure
    tampered_receipt = dict(receipt)
    tampered_receipt["human_approval"] = {"required": True, "status": "pending_human_approval", "operator_id": None}

    tamper_resp = api_client.post("/api/receipt/verify", json={"receipt": tampered_receipt})
    assert tamper_resp.status_code == 200
    tdata = tamper_resp.json()
    assert tdata["valid"] is False
    assert "FAILED" in tdata["message"]


def test_multimodal_gallery_and_analysis(api_client):
    gal_resp = api_client.get("/api/evidence/multimodal/gallery")
    assert gal_resp.status_code == 200
    gallery = gal_resp.json()
    assert len(gallery) >= 3

    # Analyze preloaded gallery item
    analyze_resp = api_client.post(
        "/api/evidence/multimodal/analyze",
        json={"asset_id": "bearing_ir_hotspot"},
    )
    assert analyze_resp.status_code == 200, analyze_resp.text
    analysis = analyze_resp.json()

    assert analysis["asset_id"] == "bearing_ir_hotspot"
    assert len(analysis["extracted_evidence"]) > 0
    assert len(analysis["model_interpretation"]) > 0
    assert len(analysis["unverified_assumptions"]) > 0
    assert analysis["untrusted_input_sanitized"] is True

    # Test uploading synthetic 1x1 GIF (magic byte check)
    gif_1x1 = base64.b64encode(b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;").decode("ascii")

    upload_resp = api_client.post(
        "/api/evidence/multimodal/analyze",
        json={
            "image_base64": gif_1x1,
            "mime_type": "image/gif",
            "component": "test_pump",
        },
    )
    assert upload_resp.status_code == 200
    up_analysis = upload_resp.json()
    assert up_analysis["untrusted_input_sanitized"] is True
    assert up_analysis["sanitized_mime_type"] == "image/gif"


@pytest.mark.live_gemini
def test_live_gemini_client_e2e():
    """Live Google GenAI test executing real Gemini calls if GEMINI_API_KEY is configured.

    Skips automatically if GEMINI_API_KEY / GOOGLE_API_KEY is not in the environment.
    """
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key or not api_key.startswith("AIzaSy"):
        pytest.skip("Skipping live Gemini test: valid Google AI Studio key (AIzaSy...) not present in environment.")

    import asyncio
    from foresight.agents.gemini import GeminiModelClient
    from foresight.config import Settings

    settings = Settings(
        FORESIGHT_LLM_PROVIDER="gemini",
        GEMINI_API_KEY=api_key,
        FORESIGHT_GEMINI_MODEL="gemini-3.8-flash",
    )
    client = GeminiModelClient(settings)

    async def _run():
        return await client.generate(
            system_prompt="You are a strict industrial telemetry analyst. Respond ONLY with valid JSON.",
            user_prompt="Analyze this telemetry: Motor speed: 1750 RPM, Stator temp: 114.5 C (trip limit 140 C), Vibration: 2.1 mm/s. Return JSON with 'risk_level' ('nominal'|'elevated'|'critical') and 'primary_stressor'.",
            response_schema={
                "type": "object",
                "properties": {
                    "risk_level": {"type": "string"},
                    "primary_stressor": {"type": "string"},
                },
                "required": ["risk_level", "primary_stressor"],
            },
        )

    res = asyncio.run(_run())
    assert res.provider == "gemini"
    assert res.model == "gemini-3.8-flash"
    assert res.input_tokens > 0
    assert res.output_tokens > 0
    assert len(res.output_text) > 0
