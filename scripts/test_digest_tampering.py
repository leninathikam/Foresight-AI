"""Security Audit: Verification Digest Tampering & Canonical Binding Test."""

from __future__ import annotations

import hashlib

from foresight.verification import CheckResult


def compute_digest(verdict: str, label: str, now_s: float, checks: list[CheckResult], evidence_ids: list[str] | None = None) -> str:
    ev_part = ",".join(sorted(evidence_ids or []))
    raw = f"{verdict}|{label}|{now_s:.1f}|{ev_part}|" + ";".join(f"{c.name}:{c.status}" for c in checks)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def test_tampering() -> dict:
    checks = [
        CheckResult(name="temperature_limit", status="pass", blocking=True, detail="OK"),
        CheckResult(name="vibration_limit", status="pass", blocking=True, detail="OK"),
    ]
    base_verdict = "accepted"
    base_label = "Inspection in 10 min"
    base_t = 5400.0
    base_ev = ["ev-100", "ev-101"]

    base_hash = compute_digest(base_verdict, base_label, base_t, checks, base_ev)

    # 1. Tamper verdict
    tamper_verdict_hash = compute_digest("rejected", base_label, base_t, checks, base_ev)

    # 2. Tamper action label / parameters
    tamper_action_hash = compute_digest(base_verdict, "Inspection in 60 min", base_t, checks, base_ev)

    # 3. Tamper timestamp
    tamper_time_hash = compute_digest(base_verdict, base_label, 5460.0, checks, base_ev)

    # 4. Tamper check status
    tampered_checks = [
        CheckResult(name="temperature_limit", status="fail", blocking=True, detail="Breach"),
        CheckResult(name="vibration_limit", status="pass", blocking=True, detail="OK"),
    ]
    tamper_check_hash = compute_digest(base_verdict, base_label, base_t, tampered_checks, base_ev)

    # 5. Tamper evidence ID
    tamper_ev_hash = compute_digest(base_verdict, base_label, base_t, checks, ["ev-999"])

    results = {
        "base_hash": base_hash,
        "tamper_verdict_detected": base_hash != tamper_verdict_hash,
        "tamper_action_detected": base_hash != tamper_action_hash,
        "tamper_timestamp_detected": base_hash != tamper_time_hash,
        "tamper_check_detected": base_hash != tamper_check_hash,
        "tamper_evidence_detected": base_hash != tamper_ev_hash,
        "cryptographic_analysis": {
            "algorithm": "SHA-256",
            "digest_length_hex": len(base_hash),
            "collision_resistance": "2^128 (cryptographically sound)",
            "threat_model_caveat": (
                "A standalone SHA-256 digest provides tamper-evidence against accidental corruption "
                "or client-side tampering only if the digest is verified against a trusted server-side "
                "session store. Against an active adversary who can rewrite both the message and digest "
                "in transit, an HMAC or Ed25519 digital signature is required."
            ),
        },
    }
    return results


if __name__ == "__main__":
    res = test_tampering()
    print("=" * 60)
    print("VERIFICATION DIGEST SECURITY & TAMPERING AUDIT")
    print("=" * 60)
    print(f"Base Digest: {res['base_hash'][:16]}...")
    print(f"• Verdict tampering detected:    {res['tamper_verdict_detected']}")
    print(f"• Action tampering detected:     {res['tamper_action_detected']}")
    print(f"• Timestamp tampering detected:  {res['tamper_timestamp_detected']}")
    print(f"• Check status tampering detect: {res['tamper_check_detected']}")
    print(f"• Evidence ID tampering detect:  {res['tamper_evidence_detected']}")
    print("\nThreat Model Caveat:")
    print(f"  {res['cryptographic_analysis']['threat_model_caveat']}")
