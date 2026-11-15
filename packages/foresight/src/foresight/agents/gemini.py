"""Google Gemini integration using the official Google Gen AI SDK (google-genai).

Provides typed tool calling, structured JSON output, conversation turn management,
token usage accounting, and graceful failure handling for the Gemini Operations Copilot.
Credentials remain strictly server-side.
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import time
import uuid
from typing import Any

from google import genai
from google.genai import errors, types

from foresight.agents.llm import FunctionCall, LLMError, LLMResponse
from foresight.config import ProviderConfig, ProviderName, Settings

log = logging.getLogger("foresight.gemini")


def _convert_schema_types(schema: Any) -> Any:
    """Recursively ensure schema property types are properly formatted for Google GenAI."""
    if not isinstance(schema, dict):
        return schema
    res = {}
    for k, v in schema.items():
        if k == "type":
            if isinstance(v, str):
                res[k] = v.upper()
            elif isinstance(v, (list, tuple)):
                types_list = [str(t) for t in v]
                has_null = "null" in types_list
                non_null = [t for t in types_list if t != "null"]
                primary = non_null[0] if non_null else "string"
                res[k] = primary.upper()
                if has_null:
                    res["nullable"] = True
            else:
                res[k] = v
        elif isinstance(v, dict):
            res[k] = _convert_schema_types(v)
        elif isinstance(v, list):
            res[k] = [_convert_schema_types(item) if isinstance(item, dict) else item for item in v]
        else:
            res[k] = v
    return res


def _build_gemini_tools(tools_defs: list[dict]) -> list[types.Tool]:
    """Convert OpenAI-style tool declarations to Google GenAI Tool declarations."""
    declarations: list[types.FunctionDeclaration] = []
    for tool in tools_defs:
        if tool.get("type") == "function":
            fn_name = tool.get("name", "")
            desc = tool.get("description", "")
            raw_params = tool.get("parameters", {})
            converted_params = _convert_schema_types(raw_params)
            fn = types.FunctionDeclaration(
                name=fn_name,
                description=desc,
                parameters=converted_params,
            )
            declarations.append(fn)
    return [types.Tool(function_declarations=declarations)] if declarations else []


class GeminiModelClient:
    """Official Google Gen AI SDK client for Gemini models in Foresight AI."""

    def __init__(
        self,
        settings: Settings,
        *,
        provider: ProviderName | None = "gemini",
        reasoning_effort: str | None = None,
        client: genai.Client | None = None,
    ) -> None:
        config = settings.provider(provider or "gemini")
        if not config.configured:
            raise LLMError("GEMINI_API_KEY is not configured")
        self.settings = settings
        self.config: ProviderConfig = config
        self.provider = config.trace_id
        self.model = config.model
        self.reasoning_effort = reasoning_effort or settings.reasoning_effort
        self._conversations: dict[str, list[types.Content]] = {}
        self._call_history: dict[str, str] = {}  # call_id -> function_name

        if client is not None:
            self._client = client
        else:
            self._client = genai.Client(api_key=config.api_key.get_secret_value())  # type: ignore[union-attr]

    def with_effort(self, effort: str) -> GeminiModelClient:
        clone = copy.copy(self)
        clone.reasoning_effort = effort
        return clone

    def cost_usd(self, input_tokens: int, cached_input_tokens: int, output_tokens: int) -> float:
        return self.config.cost_usd(input_tokens, cached_input_tokens, output_tokens)

    async def aclose(self) -> None:
        """Resource teardown if needed."""
        self._conversations.clear()
        self._call_history.clear()

    async def list_models(self) -> list[str]:
        """List models available through Google GenAI."""
        try:
            models_pager = await self._client.aio.models.list()
            return [m.name for m in models_pager if m.name]
        except Exception as exc:
            log.warning("Gemini list_models failed: %s", exc)
            return [self.model, "gemini-3.8-flash", "gemini-2.0-flash", "gemini-1.5-pro", "gemini-1.5-flash", "gemini-2.0-flash-lite"]

    async def generate(
        self,
        *,
        user_prompt: str,
        system_prompt: str | None = None,
        response_schema: dict | None = None,
        max_output_tokens: int | None = 4000,
    ) -> LLMResponse:
        """Convenience method for one-shot text/JSON generation with Gemini."""
        text_format = None
        if response_schema:
            text_format = {"type": "json_schema", "schema": response_schema}
        return await self.create_response(
            input=user_prompt,
            instructions=system_prompt,
            text_format=text_format,
            max_output_tokens=max_output_tokens,
        )

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
        """Call Gemini generate_content with tools, structured output, and stateful turn chaining."""
        start_time = time.perf_counter()

        # Build conversation history
        prior_history: list[types.Content] = []
        if previous_response_id and previous_response_id in self._conversations:
            prior_history = list(self._conversations[previous_response_id])

        # Convert input to types.Content
        new_contents: list[types.Content] = []
        if isinstance(input, list):
            # Check if this is a list of tool outputs
            is_tool_outputs = any(isinstance(x, dict) and x.get("type") == "function_call_output" for x in input)
            if is_tool_outputs:
                parts = []
                for item in input:
                    if isinstance(item, dict) and item.get("type") == "function_call_output":
                        cid = item.get("call_id", "")
                        fn_name = self._call_history.get(cid, cid)
                        raw_out = item.get("output", {})
                        if isinstance(raw_out, str):
                            try:
                                raw_out = json.loads(raw_out)
                            except Exception:
                                raw_out = {"result": raw_out}
                        elif not isinstance(raw_out, dict):
                            raw_out = {"result": raw_out}
                        parts.append(types.Part.from_function_response(name=fn_name, response=raw_out))
                if parts:
                    new_contents.append(types.Content(role="user", parts=parts))
            else:
                for msg in input:
                    if isinstance(msg, dict):
                        role = msg.get("role", "user")
                        gemini_role = "model" if role == "assistant" else "user"
                        parts = []
                        for c in msg.get("content", []):
                            if isinstance(c, dict) and c.get("type") == "input_text":
                                parts.append(types.Part.from_text(text=c.get("text", "")))
                            elif isinstance(c, str):
                                parts.append(types.Part.from_text(text=c))
                        if parts:
                            new_contents.append(types.Content(role=gemini_role, parts=parts))
        elif isinstance(input, str):
            new_contents.append(types.Content(role="user", parts=[types.Part.from_text(text=input)]))

        full_contents = prior_history + new_contents

        # Configure GenAI request
        config_kwargs: dict[str, Any] = {
            "temperature": 0.2,
        }
        if instructions:
            config_kwargs["system_instruction"] = instructions
        if max_output_tokens:
            config_kwargs["max_output_tokens"] = max_output_tokens

        if tools:
            gemini_tools = _build_gemini_tools(tools)
            if gemini_tools:
                config_kwargs["tools"] = gemini_tools

        if text_format and text_format.get("type") == "json_schema":
            schema = text_format.get("schema")
            config_kwargs["response_mime_type"] = "application/json"
            if schema:
                config_kwargs["response_schema"] = _convert_schema_types(schema)

        config = types.GenerateContentConfig(**config_kwargs)

        attempts = self.settings.llm_max_retries + 1
        last_error: Exception | None = None

        for attempt in range(1, attempts + 1):
            try:
                response = await self._client.aio.models.generate_content(
                    model=self.model,
                    contents=full_contents,
                    config=config,
                )
                latency_ms = (time.perf_counter() - start_time) * 1000.0

                resp_id = f"gemini-{uuid.uuid4().hex[:12]}"
                output_texts: list[str] = []
                function_calls: list[FunctionCall] = []
                model_parts: list[types.Part] = []

                if response.candidates:
                    candidate = response.candidates[0]
                    if candidate.content and candidate.content.parts:
                        for part in candidate.content.parts:
                            model_parts.append(part)
                            if part.text:
                                output_texts.append(part.text)
                            if part.function_call:
                                fc = part.function_call
                                cid = f"call_{uuid.uuid4().hex[:8]}"
                                self._call_history[cid] = fc.name
                                raw_args = json.dumps(fc.args or {})
                                function_calls.append(
                                    FunctionCall(call_id=cid, name=fc.name, arguments_raw=raw_args)
                                )

                # Save turn for multi-turn conversational tools
                if response.candidates and response.candidates[0].content:
                    self._conversations[resp_id] = full_contents + [response.candidates[0].content]

                usage = response.usage_metadata
                input_tokens = int(getattr(usage, "prompt_token_count", 0) or 0)
                cached_input_tokens = int(getattr(usage, "cached_content_token_count", 0) or 0)
                output_tokens = int(getattr(usage, "candidates_token_count", 0) or 0)

                return LLMResponse(
                    id=resp_id,
                    model=self.model,
                    status="completed",
                    output_text="".join(output_texts),
                    function_calls=function_calls,
                    input_tokens=input_tokens,
                    cached_input_tokens=cached_input_tokens,
                    output_tokens=output_tokens,
                    latency_ms=latency_ms,
                    raw={"usage": getattr(usage, "__dict__", {})},
                )
            except errors.APIError as exc:
                last_error = LLMError(f"Gemini API error ({exc.code}): {exc.message}", status=exc.code, retryable=(exc.code in {429, 500, 503}))
                if not last_error.retryable:
                    raise last_error
            except Exception as exc:
                last_error = LLMError(f"Gemini request failed: {type(exc).__name__}: {exc}", retryable=True)

            if attempt < attempts:
                backoff = min(0.5 * (2 ** (attempt - 1)), 10.0)
                log.warning("Gemini call failed (attempt %d/%d): %s; retrying in %.1fs", attempt, attempts, last_error, backoff)
                await asyncio.sleep(backoff)

        assert last_error is not None
        raise last_error
