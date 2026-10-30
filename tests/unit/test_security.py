from __future__ import annotations

import asyncio
import time

import pytest
from fastapi.testclient import TestClient

import foresight_api.main as main
from foresight.config import get_settings
from foresight.simulation import ScenarioId
from foresight_api.rate_limiter import RateLimitRule, SlidingWindowRateLimiter
from foresight_api.sessions import SessionError, SessionManager


@pytest.fixture
def client(monkeypatch, small_bundle):
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.setenv("MODEL_API_KEY", "")
    get_settings.cache_clear()

    monkeypatch.setattr(main, "load_or_train_bundle", lambda: small_bundle)
    with TestClient(main.app) as c:
        yield c
    get_settings.cache_clear()


def test_session_ownership_token_enforcement(client):
    # 1. Create session via client
    r = client.post("/api/sessions", json={"scenario": "cooling_degradation", "seed": 7})
    assert r.status_code == 200
    snap = r.json()
    sid = snap["status"]["session_id"]
    token = snap["owner_token"]
    assert token and len(token) > 20

    # The client has the cookie set automatically, so it can access the session:
    res_cookie = client.get(f"/api/sessions/{sid}")
    assert res_cookie.status_code == 200

    # Clear cookies on the client to simulate an unauthenticated caller
    client.cookies.clear()

    # 2. Unauthenticated client (no cookie, no header) is blocked (403 Forbidden)
    res_unauth = client.get(f"/api/sessions/{sid}")
    assert res_unauth.status_code == 403
    assert "ownership verification failed" in res_unauth.json()["detail"].lower()

    # 3. Client with the valid token in header succeeds
    res_header = client.get(f"/api/sessions/{sid}", headers={"X-Session-Token": token})
    assert res_header.status_code == 200
    assert res_header.json()["status"]["session_id"] == sid

    # 4. Tampered / wrong token is blocked (403 Forbidden)
    res_bad = client.get(f"/api/sessions/{sid}", headers={"X-Session-Token": "wrong-token-abc"})
    assert res_bad.status_code == 403

    # 5. Mutations are blocked without token
    assert client.post(f"/api/sessions/{sid}/control", json={"action": "pause"}).status_code == 403
    assert client.post(f"/api/sessions/{sid}/inject").status_code == 403
    assert client.post(f"/api/sessions/{sid}/agent/runs").status_code == 403
    assert client.delete(f"/api/sessions/{sid}").status_code == 403

    # 6. Set cookie again to verify cookie-based auth
    client.cookies.set("foresight_session_token", token)
    assert client.get(f"/api/sessions/{sid}").status_code == 200

    # 7. Authorized deletion succeeds
    assert client.delete(f"/api/sessions/{sid}").status_code == 200
    assert client.get(f"/api/sessions/{sid}").status_code == 404


@pytest.mark.asyncio
async def test_active_judge_session_preservation(small_bundle):
    settings = get_settings()
    mgr = SessionManager(small_bundle, settings)

    # Create MAX_SESSIONS (20) sessions
    sessions = []
    for i in range(20):
        s = await mgr.create(ScenarioId.COOLING_DEGRADATION, seed=i, speed=60.0)
        sessions.append(s)

    assert len(mgr.sessions) == 20

    # Ensure all 20 are active (recent last_active or active subscriber)
    for s in sessions:
        s.touch()
        assert s.is_active() is True

    # Attempting to create 21st session must NOT evict any active judge session!
    with pytest.raises(SessionError, match="Session capacity reached"):
        await mgr.create(ScenarioId.COOLING_DEGRADATION, seed=999, speed=60.0)

    assert len(mgr.sessions) == 20
    # Verify all original sessions still exist intact
    for s in sessions:
        assert s.id in mgr.sessions

    # Now make oldest session idle (no subscribers and last_active > 600s ago)
    oldest_s = sessions[0]
    oldest_s.last_active = time.monotonic() - 700.0  # 11 minutes ago
    assert oldest_s.is_active() is False

    # Now 21st create should succeed by evicting the idle session
    new_s = await mgr.create(ScenarioId.COOLING_DEGRADATION, seed=999, speed=60.0)
    assert len(mgr.sessions) == 20
    assert oldest_s.id not in mgr.sessions
    assert new_s.id in mgr.sessions

    await mgr.shutdown()


@pytest.mark.asyncio
async def test_sliding_window_rate_limiter():
    rules = {
        "general": RateLimitRule(
            max_requests=3, window_s=2.0, description="Test rate limit (3/2s)"
        ),
    }
    limiter = SlidingWindowRateLimiter(rules=rules, enabled=True)
    ip = "192.168.1.10"

    # 3 allowed
    for _ in range(3):
        allowed, _, _ = await limiter.is_allowed(ip, "/api/test", "GET")
        assert allowed is True

    # 4th rejected
    allowed, desc, retry_after = await limiter.is_allowed(ip, "/api/test", "GET")
    assert allowed is False
    assert retry_after > 0
    assert "Test rate limit" in desc

    # Wait for window to clear
    await asyncio.sleep(2.1)
    allowed, _, _ = await limiter.is_allowed(ip, "/api/test", "GET")
    assert allowed is True
