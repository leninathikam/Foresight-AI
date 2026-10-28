from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from foresight.config import get_settings


@pytest.fixture
def client(monkeypatch, small_bundle):
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.setenv("MODEL_API_KEY", "")
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


def test_full_closed_loop_flow(client):
    assert client.get("/api/health").json()["status"] == "ok"
    diag = client.get("/api/diagnostics").json()
    assert diag["llm"]["api_key_configured"] is False and "MODEL_API_KEY" not in str(diag).replace(
        "api_key_configured", ""
    )

    snap = client.post("/api/sessions", json={"scenario": "cooling_degradation", "seed": 7}).json()
    sid = snap["status"]["session_id"]
    assert len(snap["samples"]) >= 170
    client.post(f"/api/sessions/{sid}/control", json={"action": "pause"})

    assert client.post(f"/api/sessions/{sid}/inject").status_code == 200
    assert client.post(f"/api/sessions/{sid}/inject").status_code == 409  # only once
    _advance(client, sid, 80)

    a = client.get(f"/api/sessions/{sid}/assessment").json()
    assert a["available"] and a["diagnosis"][0]["label"] == "cooling"

    comp = client.post(
        f"/api/sessions/{sid}/futures",
        json={
            "actions": [
                {"type": "reduce_speed", "fraction": 0.3},
                {"type": "schedule_inspection", "delay_minutes": 10},
            ]
        },
    ).json()
    assert [b["branch_id"] for b in comp["branches"]] == ["baseline", "b1", "b2"]

    rejected = client.post(
        f"/api/sessions/{sid}/verify",
        json={"action": {"type": "reduce_speed", "fraction": 0.3}, "comparison_id": comp["id"]},
    ).json()
    assert rejected["verdict"] == "rejected"
    ok = client.post(
        f"/api/sessions/{sid}/verify",
        json={
            "action": {"type": "schedule_inspection", "delay_minutes": 10},
            "comparison_id": comp["id"],
        },
    ).json()
    assert ok["verdict"] != "rejected" and ok["requires_human_approval"]

    unapproved = client.post(
        f"/api/sessions/{sid}/interventions",
        json={"action": {"type": "reduce_load", "fraction": 0.2}},
    )
    assert unapproved.status_code == 409

    run = client.post(f"/api/sessions/{sid}/agent/runs").json()
    assert run["provider"] == "deterministic-planner"
    for _ in range(200):
        trace = client.get(f"/api/sessions/{sid}/agent/runs/{run['run_id']}").json()
        if trace["status"] != "running":
            break
        time.sleep(0.1)
    assert trace["status"] == "completed", trace.get("error")
    rec = trace["recommendation"]
    assert rec["status"] == "awaiting_approval"

    applied = client.post(
        f"/api/sessions/{sid}/interventions",
        json={
            "action": rec["action"],
            "approved": True,
            "source": "agent",
            "comparison_id": rec["comparison_id"],
        },
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["verification"]["verdict"] != "rejected"

    _advance(client, sid, 30)
    replay = client.get(f"/api/sessions/{sid}/replay-check").json()
    assert replay["deterministic"] is True and replay["interventions_replayed"] == 2

    assert client.delete(f"/api/sessions/{sid}").status_code == 200
    assert client.get(f"/api/sessions/{sid}").status_code == 404


def test_risk_alert_pauses_before_failure(client):
    sid = client.post("/api/sessions", json={"scenario": "cooling_degradation", "seed": 7}).json()[
        "status"
    ]["session_id"]
    client.post(f"/api/sessions/{sid}/control", json={"action": "pause"})
    assert client.post(f"/api/sessions/{sid}/inject").status_code == 200
    session = client.app.state.sessions.get(sid)
    session.busy = "test"  # keeps the background loop from ticking concurrently
    session.paused, session.pause_reason = False, None
    for _ in range(600):
        session._tick(60)
        if session.paused:
            break
    assert session.paused and session.pause_reason.startswith("risk alert")
    assert not session.stream.twin.state.failed
    session.busy = None


def test_input_validation(client):
    assert client.post("/api/sessions", json={"scenario": "nope"}).status_code == 422
    sid = client.post("/api/sessions", json={"scenario": "healthy"}).json()["status"]["session_id"]
    assert client.post(f"/api/sessions/{sid}/inject").status_code == 409
    bad = client.post(f"/api/sessions/{sid}/futures", json={"actions": [{"type": "teleport"}]})
    assert bad.status_code == 422
    assert (
        client.post(
            f"/api/sessions/{sid}/control", json={"action": "set_speed", "speed": 5000}
        ).status_code
        == 409
    )
