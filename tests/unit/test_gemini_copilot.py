"""Unit tests for the Gemini Operations Copilot and Google GenAI SDK integration."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from google.genai import types

from foresight.agents.gemini import (
    GeminiModelClient,
    _build_gemini_tools,
    _convert_schema_types,
)
from foresight.agents.llm import LLMError
from foresight.config import Settings


def _gemini_settings(api_key: str | None = "test-gemini-key") -> Settings:
    kw = {
        "FORESIGHT_LLM_PROVIDER": "gemini",
        "FORESIGHT_GEMINI_MODEL": "gemini-3.8-flash",
    }
    if api_key:
        kw["GEMINI_API_KEY"] = api_key
    return Settings(**kw)


@pytest.fixture(autouse=True)
def fast_sleep(monkeypatch):
    async def _sleep(_):
        return None

    monkeypatch.setattr("foresight.agents.gemini.asyncio.sleep", _sleep)


def test_schema_type_conversion():
    schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "count": {"type": "integer"},
            "sub": {
                "type": "object",
                "properties": {
                    "ratio": {"type": "number"},
                },
            },
        },
        "required": ["name"],
    }
    converted = _convert_schema_types(schema)
    assert converted["type"] == "OBJECT"
    assert converted["properties"]["name"]["type"] == "STRING"
    assert converted["properties"]["count"]["type"] == "INTEGER"
    assert converted["properties"]["sub"]["type"] == "OBJECT"
    assert converted["properties"]["sub"]["properties"]["ratio"]["type"] == "NUMBER"


def test_build_gemini_tools():
    tool_defs = [
        {
            "type": "function",
            "name": "get_machine_state",
            "description": "Get current telemetry",
            "parameters": {
                "type": "object",
                "properties": {
                    "include_history": {"type": "boolean"},
                },
            },
        }
    ]
    tools = _build_gemini_tools(tool_defs)
    assert len(tools) == 1
    assert len(tools[0].function_declarations) == 1
    fn = tools[0].function_declarations[0]
    assert fn.name == "get_machine_state"
    assert fn.description == "Get current telemetry"
    assert fn.parameters is not None


def test_unconfigured_client_raises_llmerror():
    settings = Settings(
        FORESIGHT_LLM_PROVIDER="gemini",
        GEMINI_API_KEY=None,
        GOOGLE_API_KEY=None,
    )
    with pytest.raises(LLMError, match="GEMINI_API_KEY is not configured"):
        GeminiModelClient(settings)


@pytest.mark.asyncio
async def test_gemini_client_create_response_text():
    settings = _gemini_settings()

    mock_genai_client = MagicMock()
    mock_part = types.Part.from_text(text='{"primary_hypothesis": "cooling_degradation", "confidence": 0.88}')
    mock_content = types.Content(role="model", parts=[mock_part])
    mock_candidate = types.Candidate(content=mock_content)
    mock_response = types.GenerateContentResponse(
        candidates=[mock_candidate],
        usage_metadata=types.GenerateContentResponseUsageMetadata(prompt_token_count=150, candidates_token_count=45),
    )

    mock_genai_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

    client = GeminiModelClient(settings, client=mock_genai_client)

    response = await client.create_response(
        input="Analyze this motor.",
        instructions="You are an industrial engineer.",
        text_format={"type": "json_schema", "schema": {"type": "object", "properties": {"primary_hypothesis": {"type": "string"}}}},
    )

    assert response.output_text == '{"primary_hypothesis": "cooling_degradation", "confidence": 0.88}'
    assert response.input_tokens == 150
    assert response.output_tokens == 45
    assert response.model == "gemini-3.8-flash"
    assert client.provider == "gemini"


@pytest.mark.asyncio
async def test_gemini_client_create_response_function_call():
    settings = _gemini_settings()

    mock_genai_client = MagicMock()

    # Turn 1: Model requests a tool call
    mock_call_part = types.Part.from_function_call(name="get_machine_state", args={"lookback_min": 15})
    mock_response_1 = types.GenerateContentResponse(
        candidates=[types.Candidate(content=types.Content(role="model", parts=[mock_call_part]))],
        usage_metadata=types.GenerateContentResponseUsageMetadata(prompt_token_count=200, candidates_token_count=30),
    )

    mock_genai_client.aio.models.generate_content = AsyncMock(return_value=mock_response_1)

    client = GeminiModelClient(settings, client=mock_genai_client)

    res1 = await client.create_response(
        input="Check the motor state.",
        instructions="Analyze motor telemetry.",
        tools=[{"type": "function", "name": "get_machine_state", "parameters": {"type": "object"}}],
    )

    assert len(res1.function_calls) == 1
    call = res1.function_calls[0]
    assert call.name == "get_machine_state"
    assert json.loads(call.arguments_raw) == {"lookback_min": 15}

    # Turn 2: Provide tool output, model yields final analysis
    mock_text_part = types.Part.from_text(text="Motor temperature is 112 C, elevated above normal.")
    mock_response_2 = types.GenerateContentResponse(
        candidates=[types.Candidate(content=types.Content(role="model", parts=[mock_text_part]))],
        usage_metadata=types.GenerateContentResponseUsageMetadata(prompt_token_count=280, candidates_token_count=25),
    )

    mock_genai_client.aio.models.generate_content = AsyncMock(return_value=mock_response_2)

    res2 = await client.create_response(
        input=[{"type": "function_call_output", "call_id": call.call_id, "output": json.dumps({"temperature_c": 112.4})}],
        instructions="Analyze motor telemetry.",
        previous_response_id=res1.id,
    )

    assert res2.output_text == "Motor temperature is 112 C, elevated above normal."
    assert len(res2.function_calls) == 0


@pytest.mark.asyncio
async def test_gemini_client_error_handling_graceful():
    settings = _gemini_settings()

    mock_genai_client = MagicMock()
    mock_genai_client.aio.models.generate_content = AsyncMock(side_effect=Exception("Google API connection refused"))

    client = GeminiModelClient(settings, client=mock_genai_client)

    with pytest.raises(LLMError, match="Gemini request failed"):
        await client.create_response(
            input="User",
            instructions="System",
        )
