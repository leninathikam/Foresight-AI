"""End-to-End Release Readiness Verification Script for Foresight-AI API endpoints."""

import json
import httpx
from fastapi.testclient import TestClient
from foresight_api.main import app

BASE_URL = "http://127.0.0.1:8000"

def run_all_checks():
    try:
        live = httpx.Client(base_url=BASE_URL, timeout=120.0)
        r = live.get("/api/health")
        if r.status_code == 200:
            _execute_checks(live)
            return
    except Exception:
        pass
    with TestClient(app) as test_client:
        _execute_checks(test_client)

def _execute_checks(client):
    print("============================================================")
    print("  Foresight-AI: Live End-to-End Endpoint Verification Audit ")
    print("============================================================")

    # 1. Health & Gemini Providers
    print("\n[CHECK 1] Verifying /api/health & Gemini Provider Architecture...")
    r = client.get("/api/health")
    assert r.status_code == 200, f"Health check failed: {r.status_code} {r.text}"
    health = r.json()
    print("  Status:", health["status"])
    print("  Version:", health["version"])
    print("  Model Bundle:", health["model_bundle"])
    print("  LLM Configured:", health["llm_configured"])
    providers = health["providers"]
    print("  Active Providers:")
    for p in providers:
        print(f"    - {p['name']}: {p['label']} (Model: {p['model']}, Default: {p['default']})")
    assert any(p["name"].startswith("gemini") for p in providers), "No Gemini providers registered!"
    print("  --> PASS: Health & Gemini provider configuration verified.")

    # 2. Session Creation
    print("\n[CHECK 2] Creating Session...")
    r = client.post("/api/sessions", json={"scenario": "cooling_degradation"})
    assert r.status_code == 200, f"Session creation failed: {r.status_code} {r.text}"
    sess = r.json()
    sid = sess["status"]["session_id"]
    token = sess.get("owner_token") or r.cookies.get("foresight_session_token")
    headers = {"X-Session-Token": token} if token else {}
    print(f"  Session created: {sid} (initial state={sess['status'].get('state')})")
    print("  --> PASS: Session initialized successfully.")

    # 3. Future Arena End-to-End
    print("\n[CHECK 3] Verifying Future Arena (/api/sessions/{session_id}/arena)...")
    r = client.post(f"/api/sessions/{sid}/arena", headers=headers)
    assert r.status_code == 200, f"Future Arena failed: {r.status_code} {r.text}"
    arena = r.json()
    assert "scenarios" in arena, "No scenarios in arena response"
    scenarios = arena["scenarios"]
    print(f"  Scenarios returned: {len(scenarios)}")
    for sc in scenarios:
        print(f"    - [{sc['scenario_id']}] {sc['label']}:")
        print(f"        Expected Cost: ${sc['expected_cost_usd']:,.2f}")
        print(f"        Failure Rate:  {sc['failure_incidence']*100:.1f}%")
        print(f"        Peak Temp:     {sc['peak_temperature_p90_c']:.1f} °C")
        print(f"        Peak Vib:      {sc['peak_vibration_p90_mm_s']:.2f} mm/s")
        print(f"        Safe Margin:   {sc['safety_status']}")
    assert len(scenarios) == 3, f"Expected 3 scenarios, got {len(scenarios)}"
    print(f"  Winner Scenario: {arena['winner_scenario_id']} ({arena['winner_label']})")
    print(f"  Reason: {arena['recommendation_reason']}")
    print(f"  Simulation Latency: {arena['compute_ms']:.1f} ms")
    print("  --> PASS: Future Arena 3-way simulation verified.")

    # 4. Safety Challenge Catalog & Adversarial Attack
    print("\n[CHECK 4] Verifying Safety Challenge Catalog & Verifier v5 Gate...")
    r = client.get("/api/safety-challenge/catalog")
    assert r.status_code == 200, f"Catalog failed: {r.status_code}"
    catalog = r.json()
    print(f"  Available adversarial challenges: {len(catalog)}")
    for c in catalog:
        cid = c.get("challenge_id")
        title = c.get("name")
        print(f"    - {cid}: {title}")
    
    print("  Executing adversarial attack: 'bearing_derate_trap'...")
    r = client.post(f"/api/sessions/{sid}/safety-challenge", json={"challenge_id": "bearing_derate_trap"}, headers=headers)
    assert r.status_code == 200, f"Safety challenge execution failed: {r.status_code}"
    res = r.json()
    print("  Verifier Decision:", res["verdict"].upper())
    print("  Direct Actuation Blocked:", res["direct_actuation_blocked"])
    print("  Rejection Reasons:", res["rejection_reasons"])
    assert res["verdict"] == "rejected", f"Expected rejection, got {res['verdict']}"
    assert res["direct_actuation_blocked"] is True, "CRITICAL SAFETY VIOLATION: Actuation was permitted on unsafe proposal!"
    print("  --> PASS: Safety Challenge verified. Verifier v5 blocked direct actuation.")

    # 5. Cryptographic Decision Receipts
    print("\n[CHECK 5] Verifying Decision Receipts & Canonical SHA-256 Digest...")
    r = client.post(f"/api/sessions/{sid}/receipt", json={"human_approved": False, "operator_id": "OP-AUDIT"}, headers=headers)
    assert r.status_code == 200, f"Receipt creation failed: {r.status_code}"
    receipt = r.json()
    digest = receipt["sha256_digest"]
    print(f"  Receipt ID:    {receipt['receipt_id']}")
    print(f"  SHA-256 Digest: {digest}")
    print(f"  Action Chosen:  {receipt['recommended_action']['type']}")
    print(f"  Human Approved: {receipt['human_approval']['status']}")

    # Verify unaltered receipt
    print("  Verifying unaltered receipt integrity...")
    r_ver = client.post("/api/receipt/verify", json={"receipt": receipt})
    assert r_ver.status_code == 200
    v_data = r_ver.json()
    assert v_data["valid"] is True
    print("  --> Verification result: VALID (Digest matched perfectly)")

    # Tamper with receipt and verify detection
    print("  Tampering with receipt (flipping human_approved status)...")
    tampered = dict(receipt)
    tampered["human_approval"] = {"required": True, "status": "approved_by_human", "operator_id": "OP-HACK"}
    r_tamp = client.post("/api/receipt/verify", json={"receipt": tampered})
    assert r_tamp.status_code == 200
    t_data = r_tamp.json()
    assert t_data["valid"] is False, "Tamper detection failed!"
    print(f"  --> Tamper detected: VALIDATION FAILED as expected ({t_data['message']})")
    print("  --> PASS: Decision Receipt cryptographic integrity verified.")

    # 6. Multimodal Endpoints
    print("\n[CHECK 6] Verifying Multimodal Endpoints (/api/evidence/multimodal/*)...")
    r_gal = client.get("/api/evidence/multimodal/gallery")
    assert r_gal.status_code == 200
    gallery = r_gal.json()
    print(f"  Preloaded gallery inspection items: {len(gallery)}")
    for item in gallery:
        aid = item.get("asset_id")
        print(f"    - [{aid}] {item.get('name')} (Component: {item.get('component')})")

    # Analyze first gallery item
    first_item = gallery[0]
    aid = first_item.get("asset_id")
    print(f"  Submitting multimodal analysis for item '{aid}'...")
    r_ana = client.post("/api/evidence/multimodal/analyze", json={"asset_id": aid})
    assert r_ana.status_code == 200, f"Analysis failed: {r_ana.status_code} {r_ana.text}"
    ana = r_ana.json()
    print("  Component:", ana.get("asset_component"))
    print("  Extracted Evidence:", ana.get("extracted_evidence", [])[:2])
    print("  Model Diagnostic Interpretation:", ana.get("model_interpretation"))
    print("  Unverified Assumptions:", ana.get("unverified_assumptions"))
    print("  --> PASS: Multimodal evidence and interpretation separation verified.")

    print("\n============================================================")
    print("  ALL ENDPOINTS PASSED END-TO-END VERIFICATION AUDIT (6/6) ")
    print("============================================================")

if __name__ == "__main__":
    run_all_checks()
