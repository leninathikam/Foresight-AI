from __future__ import annotations

import json

import httpx
import pytest

from foresight.agents.llm import LLMError, MetaModelClient, parse_response
from foresight.config import Settings


def _settings(**kw) -> Settings:
    return Settings(MODEL_API_KEY="test-key", FORESIGHT_LLM_MAX_RETRIES=2, **kw)


@pytest.fixture(autouse=True)
def fast_sleep(monkeypatch):
    async def _sleep(_):
        return None

    monkeypatch.setattr("foresight.agents.llm.asyncio.sleep", _sleep)


def test_parse_response_extracts_text_calls_and_usage():
    payload = {
        "id": "resp_1",
        "model": "muse-spark-1.3",
        "status": "completed",
        "output": [
            {"type": "reasoning", "summary": []},
            {
                "type": "function_call",
                "call_id": "call_1",
                "name": "get_machine_state",
                "arguments": "{}",
            },
            {"type": "message", "content": [{"type": "output_text", "text": "hello"}]},
        ],
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }
    r = parse_response(payload, 12.0)
    assert r.output_text == "hello"
    assert (
        r.function_calls[0].name == "get_machine_state" and r.function_calls[0].call_id == "call_1"
    )
    assert (r.input_tokens, r.output_tokens) == (10, 5)


def test_malformed_tool_arguments_raise():
    r = parse_response(
        {
            "output": [
                {"type": "function_call", "call_id": "c", "name": "x", "arguments": "{not json"}
            ]
        },
        0,
    )
    with pytest.raises(LLMError):
        r.function_calls[0].arguments()


async def test_request_shape_and_auth_header():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers["authorization"]
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"id": "r", "status": "completed", "output": []})

    client = MetaModelClient(_settings(), transport=httpx.MockTransport(handler))
    await client.create_response(
        input="hi",
        tools=[{"type": "function", "name": "t", "parameters": {}}],
        text_format=None,
        previous_response_id="prev",
    )
    assert seen["auth"] == "Bearer test-key"
    assert seen["url"] == "https://api.meta.ai/v1/responses"
    body = seen["body"]
    assert body["model"] == "muse-spark-1.3"
    assert body["previous_response_id"] == "prev"
    assert body["reasoning"] == {"effort": "medium"}
    assert "tool_choice" not in body  # only "auto" is supported; leave it at the default


async def test_retries_rate_limit_then_succeeds():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(
                429, headers={"retry-after": "0"}, json={"error": {"message": "slow down"}}
            )
        return httpx.Response(200, json={"id": "ok", "status": "completed", "output": []})

    client = MetaModelClient(_settings(), transport=httpx.MockTransport(handler))
    r = await client.create_response(input="x")
    assert r.id == "ok" and calls["n"] == 2


async def test_does_not_retry_bad_request():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(400, json={"error": {"message": "bad schema"}})

    client = MetaModelClient(_settings(), transport=httpx.MockTransport(handler))
    with pytest.raises(LLMError, match="bad schema") as exc:
        await client.create_response(input="x")
    assert exc.value.status == 400 and calls["n"] == 1


async def test_provider_outage_exhausts_retries():
    def handler(request):
        raise httpx.ConnectTimeout("timeout")

    client = MetaModelClient(_settings(), transport=httpx.MockTransport(handler))
    with pytest.raises(LLMError, match="ConnectTimeout"):
        await client.create_response(input="x")


def test_client_refuses_to_start_without_key():
    with pytest.raises(LLMError):
        MetaModelClient(Settings(MODEL_API_KEY=None))
