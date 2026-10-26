"""Foresight AI HTTP API.

Run: uv run uvicorn foresight_api.main:app --port 8000
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any, Literal

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, ValidationError

from foresight import __version__
from foresight.agents import LLMError, MetaModelClient
from foresight.artifacts import MODEL_PATH, REPORTS_DIR, load_or_train_bundle
from foresight.branching import ACTION_ADAPTER, OBJECTIVE_DEFINITION
from foresight.config import Settings, get_settings
from foresight.prediction import FEATURE_NAMES
from foresight.prediction.features import FEATURE_DESCRIPTIONS
from foresight.simulation import DEFAULT_ECONOMICS, DEFAULT_MOTOR, SCENARIOS, ScenarioId
from foresight.verification import DEFAULT_POLICY
from foresight_api.logging_setup import configure_logging
from foresight_api.sessions import LiveSession, SessionError, SessionManager, parse_action

log = logging.getLogger("foresight.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    settings = get_settings()
    started = time.perf_counter()
    bundle = await asyncio.to_thread(load_or_train_bundle)
    log.info(
        "risk bundle ready", extra={"latency_ms": round((time.perf_counter() - started) * 1000)}
    )
    app.state.settings = settings
    app.state.bundle = bundle
    app.state.sessions = SessionManager(bundle, settings)
    app.state.llm = MetaModelClient(settings) if settings.llm_configured else None
    app.state.model_check = None
    yield
    await app.state.sessions.shutdown()
    if app.state.llm:
        await app.state.llm.aclose()


app = FastAPI(title="Foresight AI", version=__version__, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origin_list,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type"],
)


@app.middleware("http")
async def request_logging(request: Request, call_next):
    rid = uuid.uuid4().hex[:8]
    start = time.perf_counter()
    response = await call_next(request)
    if not request.url.path.endswith("/stream"):
        log.info(
            "request",
            extra={
                "request_id": rid,
                "path": f"{request.method} {request.url.path}",
                "status": response.status_code,
                "latency_ms": round((time.perf_counter() - start) * 1000, 1),
            },
        )
    return response


@app.exception_handler(SessionError)
async def session_error_handler(_: Request, exc: SessionError):
    return JSONResponse(status_code=409, content={"detail": str(exc)})


def _session(request: Request, session_id: str) -> LiveSession:
    try:
        return request.app.state.sessions.get(session_id)
    except KeyError:
        raise HTTPException(404, f"Session {session_id} not found") from None


def _action(payload: dict) -> Any:
    try:
        return parse_action(payload)
    except ValidationError as exc:
        raise HTTPException(422, f"Invalid action: {exc.errors()[0]['msg']}") from exc


# ---------------------------------------------------------------------- meta


@app.get("/api/health")
async def health(request: Request):
    return {
        "status": "ok",
        "version": __version__,
        "model_bundle": request.app.state.bundle.version,
        "active_sessions": len(request.app.state.sessions.sessions),
        "llm_configured": request.app.state.settings.llm_configured,
    }


@app.get("/api/diagnostics")
async def diagnostics(request: Request):
    s: Settings = request.app.state.settings
    return {
        "llm": {
            "provider": "Meta Model API (Responses API)",
            "base_url": s.meta_api_base_url,
            "reasoning_model": s.reasoning_model,
            "reasoning_effort": s.reasoning_effort,
            "api_key_configured": s.llm_configured,
            "timeout_s": s.llm_timeout_s,
            "max_retries": s.llm_max_retries,
            "agent_max_tool_calls": s.agent_max_tool_calls,
            "agent_max_revisions": s.agent_max_revisions,
            "last_check": request.app.state.model_check,
        },
        "predictive_models": request.app.state.bundle.metadata,
        "model_path": str(MODEL_PATH),
    }


@app.post("/api/diagnostics/model-check")
async def model_check(request: Request):
    """Live connectivity smoke test: lists models and makes one minimal Responses call."""
    llm: MetaModelClient | None = request.app.state.llm
    if llm is None:
        result = {"ok": False, "error": "MODEL_API_KEY not configured", "checked_at": time.time()}
        request.app.state.model_check = result
        return result
    out: dict[str, Any] = {"checked_at": time.time(), "model": llm.model}
    try:
        start = time.perf_counter()
        models = await llm.list_models()
        out["models_listed"] = models
        out["model_available"] = llm.model in models
        out["list_latency_ms"] = round((time.perf_counter() - start) * 1000, 1)
    except (LLMError, httpx.HTTPError) as exc:
        out["list_error"] = str(exc)
    try:
        resp = await llm.create_response(
            input="Reply with the single word: ready", max_output_tokens=64
        )
        out |= {
            "ok": True,
            "response_latency_ms": round(resp.latency_ms, 1),
            "response_text": resp.output_text[:80],
            "input_tokens": resp.input_tokens,
            "output_tokens": resp.output_tokens,
        }
    except LLMError as exc:
        out |= {"ok": False, "error": str(exc)}
    request.app.state.model_check = out
    return out


@app.get("/api/model-info")
async def model_info():
    return {
        "motor": DEFAULT_MOTOR.__dict__,
        "economics": DEFAULT_ECONOMICS.__dict__,
        "policy": DEFAULT_POLICY.model_dump(),
        "objective": OBJECTIVE_DEFINITION,
        "features": [{"name": n, "description": FEATURE_DESCRIPTIONS[n]} for n in FEATURE_NAMES],
    }


@app.get("/api/scenarios")
async def scenarios():
    return [s.model_dump() for s in SCENARIOS.values()]


@app.get("/api/evaluation")
async def evaluation():
    path = REPORTS_DIR / "evaluation.json"
    if not path.exists():
        raise HTTPException(
            404, "No evaluation report yet. Run: uv run python scripts/run_evaluation.py"
        )
    return json.loads(path.read_text())


# ---------------------------------------------------------------------- sessions


class CreateSession(BaseModel):
    scenario: ScenarioId = ScenarioId.COOLING_DEGRADATION
    seed: int = Field(7, ge=0, le=1_000_000)
    speed: float | None = Field(None, ge=1, le=600)


@app.post("/api/sessions")
async def create_session(request: Request, body: CreateSession):
    session = await request.app.state.sessions.create(body.scenario, body.seed, body.speed)
    return session.snapshot()


@app.get("/api/sessions/{session_id}")
async def get_session(request: Request, session_id: str):
    return _session(request, session_id).snapshot()


@app.delete("/api/sessions/{session_id}")
async def delete_session(request: Request, session_id: str):
    _session(request, session_id)
    await request.app.state.sessions.delete(session_id)
    return {"deleted": session_id}


@app.get("/api/sessions/{session_id}/stream")
async def stream_session(request: Request, session_id: str):
    session = _session(request, session_id)
    queue = session.subscribe()

    async def events():
        try:
            yield f"event: status\ndata: {json.dumps(session.status())}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=15.0)
                except TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                yield f"event: {msg['type']}\ndata: {json.dumps(msg['data'], default=str)}\n\n"
        finally:
            session.unsubscribe(queue)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


class ControlBody(BaseModel):
    action: Literal["pause", "resume", "set_speed"]
    speed: float | None = None


@app.post("/api/sessions/{session_id}/control")
async def control(request: Request, session_id: str, body: ControlBody):
    return _session(request, session_id).control(body.action, body.speed)


@app.post("/api/sessions/{session_id}/inject")
async def inject(request: Request, session_id: str):
    return _session(request, session_id).inject_fault()


@app.get("/api/sessions/{session_id}/assessment")
async def assessment(request: Request, session_id: str):
    a = _session(request, session_id).assessment
    if a is None:
        raise HTTPException(404, "No assessment yet")
    return a.model_dump()


@app.get("/api/sessions/{session_id}/estimate")
async def estimate(request: Request, session_id: str):
    return _session(request, session_id).estimate().model_dump()


class FuturesBody(BaseModel):
    actions: list[dict] = Field(min_length=1, max_length=6)
    horizon_min: float = Field(180.0, ge=30, le=360)
    members: int = Field(8, ge=4, le=32)
    state_source: Literal["estimated", "oracle"] = "estimated"


@app.post("/api/sessions/{session_id}/futures")
async def futures(request: Request, session_id: str, body: FuturesBody):
    session = _session(request, session_id)
    actions = [_action(a) for a in body.actions]
    comp = await session.run_futures(actions, body.horizon_min, body.members, body.state_source)
    return comp.model_dump()


@app.get("/api/sessions/{session_id}/futures/{comparison_id}")
async def get_futures(request: Request, session_id: str, comparison_id: str):
    comp = _session(request, session_id).comparisons.get(comparison_id)
    if comp is None:
        raise HTTPException(404, "Comparison not found")
    return comp.model_dump()


class VerifyBody(BaseModel):
    action: dict
    comparison_id: str | None = None
    claimed_failure_mode: Literal["thermal", "bearing", "overload", "none", "unknown"] = "unknown"


@app.post("/api/sessions/{session_id}/verify")
async def verify_endpoint(request: Request, session_id: str, body: VerifyBody):
    session = _session(request, session_id)
    result, vid = session.verify_action(
        _action(body.action), body.comparison_id, body.claimed_failure_mode
    )
    return {"verification_id": vid, **result.model_dump()}


@app.post("/api/sessions/{session_id}/agent/runs")
async def start_agent(request: Request, session_id: str):
    session = _session(request, session_id)
    trace = await session.run_agent(request.app.state.llm)
    return {"run_id": trace.run_id, "provider": trace.provider, "notice": trace.notice}


@app.get("/api/sessions/{session_id}/agent/runs/{run_id}")
async def get_agent_run(request: Request, session_id: str, run_id: str):
    trace = _session(request, session_id).agent_runs.get(run_id)
    if trace is None:
        raise HTTPException(404, "Agent run not found")
    return trace.model_dump()


class InterventionBody(BaseModel):
    action: dict
    approved: bool = False
    source: Literal["user", "agent"] = "user"
    comparison_id: str | None = None


@app.post("/api/sessions/{session_id}/interventions")
async def intervene(request: Request, session_id: str, body: InterventionBody):
    session = _session(request, session_id)
    return session.apply_intervention(
        _action(body.action), body.approved, body.source, body.comparison_id
    )


@app.get("/api/sessions/{session_id}/replay-check")
async def replay_check(request: Request, session_id: str):
    session = _session(request, session_id)
    return await asyncio.to_thread(session.replay_check)


@app.get("/api/actions/schema")
async def action_schema():
    return ACTION_ADAPTER.json_schema()
