"""Live Meta agent smoke: create session, inject fault, run agent. No secrets printed."""

from __future__ import annotations

import time

import httpx

BASE = "http://127.0.0.1:8000"


def main() -> None:
    with httpx.Client(base_url=BASE, timeout=300.0) as c:
        s = c.post(
            "/api/sessions",
            json={"scenario": "cooling_degradation", "seed": 7, "speed": 120},
        )
        s.raise_for_status()
        body = s.json()
        status = body.get("status") or body
        sid = status.get("session_id") or body.get("session_id") or body.get("id")
        print("sid", sid)
        c.post(f"/api/sessions/{sid}/inject").raise_for_status()
        c.post(
            f"/api/sessions/{sid}/control", json={"action": "set_speed", "speed": 300}
        ).raise_for_status()
        print("waiting for fault to develop...")
        time.sleep(25)
        snap = c.get(f"/api/sessions/{sid}").json()
        st = snap.get("status") or {}
        a = snap.get("assessment") or {}
        horiz = {h["horizon_min"]: h["probability"] for h in a.get("horizons", [])}
        diag = (a.get("diagnosis") or [{}])[0]
        print(
            f"t_s={st.get('sim_time_s')} risk={horiz} "
            f"diag={diag.get('label')} p={diag.get('probability')}"
        )
        print("running Meta agent...")
        run = c.post(f"/api/sessions/{sid}/agent/runs")
        run.raise_for_status()
        run_body = run.json()
        print("run", run_body)
        rid = run_body["run_id"]
        deadline = time.time() + 280
        while True:
            trace = c.get(f"/api/sessions/{sid}/agent/runs/{rid}").json()
            status = trace.get("status")
            stage = trace.get("stage")
            print(f"  poll status={status} stage={stage}")
            if status in {"completed", "failed", "done"} or stage in {"DONE", "FAILED"}:
                break
            if time.time() > deadline:
                print("TIMEOUT waiting for agent")
                break
            time.sleep(3)
        print("provider", trace.get("provider"), "status", trace.get("status"), "stage", stage)
        steps = trace.get("steps") or []
        print("n_steps", len(steps))
        for st in steps:
            print(
                f"  step#{st.get('seq')} {st.get('stage')} {st.get('kind')} "
                f"{st.get('name')} ok={st.get('ok')} :: {st.get('result_summary', '')[:120]}"
            )
        rec = trace.get("recommendation") or {}
        print("rec_status", rec.get("status"), "action", rec.get("action"))
        print("rejected", len(trace.get("rejected") or []))
        print("notice", trace.get("notice"))
        print("error", trace.get("error"))
        usage = trace.get("usage") or {}
        print(
            "cost",
            usage.get("estimated_cost_usd"),
            "tokens_in",
            usage.get("input_tokens"),
            "tokens_out",
            usage.get("output_tokens"),
            "latency_ms",
            trace.get("latency_ms"),
        )


if __name__ == "__main__":
    main()
