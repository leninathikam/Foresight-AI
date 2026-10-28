"""Responses-API client for Meta models, with bounded retries and timeouts.

Request/response shapes follow https://dev.meta.ai/docs (Responses API, tool calling,
structured output): flat ``function`` tools, ``function_call`` output items answered with
``function_call_output`` input items plus ``previous_response_id``, and structured output via
``text.format`` of type ``json_schema``. ``tool_choice`` is left at its only supported value,
``"auto"``.

The same wire format is served by the Meta Model API (Muse Spark) and by Fireworks AI
(Muse Spark Open, https://docs.fireworks.ai/guides/response-api); ``ProviderConfig`` selects
the endpoint, key, model and prices.
"""

from __future__ import annotations

import asyncio
import contextlib
import copy
import json
import logging
import random
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from foresight.config import ProviderConfig, ProviderName, Settings

log = logging.getLogger("foresight.llm")

RETRYABLE_STATUS = {408, 409, 429, 500, 502, 503, 504}


class LLMError(RuntimeError):
    def __init__(self, message: str, status: int | None = None, retryable: bool = False) -> None:
        super().__init__(message)
        self.status = status
        self.retryable = retryable


@dataclass
class FunctionCall:
    call_id: str
    name: str
    arguments_raw: str

    def arguments(self) -> dict[str, Any]:
        try:
            parsed = json.loads(self.arguments_raw or "{}")
        except json.JSONDecodeError as exc:
            raise LLMError(f"Tool '{self.name}' arguments are not valid JSON: {exc}") from exc
        if not isinstance(parsed, dict):
            raise LLMError(f"Tool '{self.name}' arguments must be a JSON object")
        return parsed


@dataclass
class LLMResponse:
    id: str
    model: str
    status: str
    output_text: str
    function_calls: list[FunctionCall]
    input_tokens: int
    output_tokens: int
    latency_ms: float
    cached_input_tokens: int = 0
    raw: dict = field(repr=False, default_factory=dict)


def parse_response(payload: dict, latency_ms: float) -> LLMResponse:
    texts: list[str] = []
    calls: list[FunctionCall] = []
    for item in payload.get("output", []) or []:
        kind = item.get("type")
        if kind == "function_call":
            calls.append(
                FunctionCall(
                    call_id=item.get("call_id") or item.get("id", ""),
                    name=item.get("name", ""),
                    arguments_raw=item.get("arguments", "") or "",
                )
            )
        elif kind == "message":
            for part in item.get("content", []) or []:
                if part.get("type") == "output_text":
                    texts.append(part.get("text", ""))
    usage = payload.get("usage") or {}
    details = usage.get("input_tokens_details") or {}
    return LLMResponse(
        id=payload.get("id", ""),
        model=payload.get("model", ""),
        status=payload.get("status", ""),
        output_text="".join(texts),
        function_calls=calls,
        input_tokens=int(usage.get("input_tokens", 0) or 0),
        output_tokens=int(usage.get("output_tokens", 0) or 0),
        cached_input_tokens=int(details.get("cached_tokens", 0) or 0),
        latency_ms=latency_ms,
        raw=payload,
    )


_KEY_ENV = {"meta": "MODEL_API_KEY", "fireworks": "FIREWORKS_API_KEY"}


class ModelClient:
    def __init__(
        self,
        settings: Settings,
        transport: httpx.AsyncBaseTransport | None = None,
        *,
        provider: ProviderName | None = None,
        reasoning_effort: str | None = None,
    ) -> None:
        config = settings.provider(provider)
        if not config.configured:
            raise LLMError(f"{_KEY_ENV[config.name]} is not configured")
        self.settings = settings
        self.config: ProviderConfig = config
        self.provider = config.trace_id
        self.model = config.model
        self.reasoning_effort = self._check_effort(reasoning_effort or settings.reasoning_effort)
        self._client = httpx.AsyncClient(
            base_url=config.base_url,
            headers={
                "Authorization": f"Bearer {config.api_key.get_secret_value()}",  # type: ignore[union-attr]
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(settings.llm_timeout_s, connect=10.0),
            transport=transport,
        )
        self._owns_client = True

    def _check_effort(self, effort: str) -> str:
        if effort not in self.config.efforts:
            raise LLMError(
                f"Reasoning effort {effort!r} is not supported by {self.config.label}; "
                f"use one of {list(self.config.efforts)}"
            )
        return effort

    def with_effort(self, effort: str) -> ModelClient:
        """A view of this client with a different reasoning effort; shares the HTTP pool."""
        clone = copy.copy(self)
        clone.reasoning_effort = self._check_effort(effort)
        clone._owns_client = False
        return clone

    def cost_usd(self, input_tokens: int, cached_input_tokens: int, output_tokens: int) -> float:
        return self.config.cost_usd(input_tokens, cached_input_tokens, output_tokens)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def create_response(
        self,
        *,
        input: Any,
        instructions: str | None = None,
        tools: list[dict] | None = None,
        text_format: dict | None = None,
        previous_response_id: str | None = None,
        max_output_tokens: int | None = 4000,
        parallel_tool_calls: bool = True,
    ) -> LLMResponse:
        body: dict[str, Any] = {
            "model": self.model,
            "input": input,
            "reasoning": {"effort": self.reasoning_effort},
        }
        if instructions:
            body["instructions"] = instructions
        if tools:
            body["tools"] = tools
            body["parallel_tool_calls"] = parallel_tool_calls
        if text_format:
            body["text"] = {"format": text_format}
        if previous_response_id:
            body["previous_response_id"] = previous_response_id
        if max_output_tokens:
            body["max_output_tokens"] = max_output_tokens
        return await self._post("/responses", body)

    async def list_models(self) -> list[str]:
        resp = await self._client.get("/models")
        if resp.status_code >= 400:
            raise LLMError(f"GET /models failed: HTTP {resp.status_code}", status=resp.status_code)
        data = resp.json()
        return [m.get("id", "") for m in data.get("data", [])]

    async def _post(self, path: str, body: dict) -> LLMResponse:
        attempts = self.settings.llm_max_retries + 1
        delay = 0.5
        last_error: LLMError | None = None
        for attempt in range(1, attempts + 1):
            start = time.perf_counter()
            try:
                resp = await self._client.post(path, json=body)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = LLMError(f"{type(exc).__name__}: {exc}", retryable=True)
            else:
                latency = (time.perf_counter() - start) * 1000.0
                if resp.status_code < 400:
                    try:
                        payload = resp.json()
                    except json.JSONDecodeError as exc:
                        raise LLMError("Model API returned non-JSON body") from exc
                    if payload.get("status") == "failed":
                        raise LLMError(f"Response failed: {payload.get('error')}")
                    return parse_response(payload, latency)
                message = _error_message(resp)
                retryable = resp.status_code in RETRYABLE_STATUS
                last_error = LLMError(
                    f"HTTP {resp.status_code}: {message}",
                    status=resp.status_code,
                    retryable=retryable,
                )
                if not retryable:
                    raise last_error
                retry_after = resp.headers.get("retry-after")
                if retry_after:
                    with contextlib.suppress(ValueError):
                        delay = max(delay, float(retry_after))
            if attempt < attempts:
                sleep_for = delay + random.uniform(0, delay / 2)
                log.warning(
                    "model call failed (%s); retry %d in %.1fs", last_error, attempt, sleep_for
                )
                await asyncio.sleep(sleep_for)
                delay = min(delay * 2, 20.0)
        assert last_error is not None
        raise last_error


MetaModelClient = ModelClient


def _error_message(resp: httpx.Response) -> str:
    try:
        data = resp.json()
        err = data.get("error", data)
        if isinstance(err, dict):
            return str(err.get("message") or err)
        return str(err)
    except json.JSONDecodeError:
        return resp.text[:300]
