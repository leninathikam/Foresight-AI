"""Probe Fireworks' Responses API with Muse Spark Open for the features the agent relies on.

Reads FIREWORKS_API_KEY from .env; never prints it.
"""

from __future__ import annotations

import json
import time

import httpx
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

MODEL = "accounts/fireworks/models/muse-spark-open"


class _Env(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    key: SecretStr = Field(alias="FIREWORKS_API_KEY")


def _post(client: httpx.Client, body: dict) -> dict | None:
    t0 = time.perf_counter()
    r = client.post("/responses", json=body)
    ms = (time.perf_counter() - t0) * 1000
    if r.status_code >= 400:
        print(f"  HTTP {r.status_code} in {ms:.0f} ms: {r.text[:400]}")
        return None
    p = r.json()
    kinds = [o.get("type") for o in p.get("output", [])]
    print(f"  ok {ms:.0f} ms status={p.get('status')} output={kinds} usage={p.get('usage')}")
    return p


def _text(p: dict) -> str:
    return "".join(
        c.get("text", "")
        for o in p.get("output", [])
        if o.get("type") == "message"
        for c in o.get("content", [])
        if c.get("type") == "output_text"
    )


def main() -> None:
    env = _Env()  # type: ignore[call-arg]
    client = httpx.Client(
        base_url="https://api.fireworks.ai/inference/v1",
        headers={"Authorization": f"Bearer {env.key.get_secret_value()}"},
        timeout=120,
    )
    base = {"model": MODEL, "reasoning": {"effort": "low"}, "max_output_tokens": 2048}

    print("1. plain text")
    p = _post(client, {**base, "input": "Reply with exactly: OK"})
    if p:
        print("  text:", repr(_text(p)[:80]))

    print("2. structured output (text.format json_schema)")
    schema = {
        "type": "json_schema",
        "name": "verdict",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {"mode": {"type": "string", "enum": ["thermal", "bearing"]}},
            "required": ["mode"],
            "additionalProperties": False,
        },
    }
    p = _post(
        client,
        {**base, "input": "Winding temperature is rising. Which mode?", "text": {"format": schema}},
    )
    if p:
        txt = _text(p)
        try:
            print("  parsed:", json.loads(txt))
        except json.JSONDecodeError:
            print("  NOT JSON:", repr(txt[:200]))

    print("3. tool call + function_call_output via previous_response_id")
    tool = {
        "type": "function",
        "name": "get_temperature",
        "description": "Current winding temperature in C",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    }
    p = _post(
        client,
        {
            **base,
            "input": "Call get_temperature, then tell me the value.",
            "tools": [tool],
            "parallel_tool_calls": True,
        },
    )
    calls = [o for o in (p or {}).get("output", []) if o.get("type") == "function_call"]
    if calls:
        print("  call:", calls[0].get("name"), calls[0].get("arguments"))
        p2 = _post(
            client,
            {
                **base,
                "previous_response_id": p["id"],
                "tools": [tool],
                "input": [
                    {
                        "type": "function_call_output",
                        "call_id": calls[0].get("call_id"),
                        "output": json.dumps({"temperature_c": 121.7}),
                    }
                ],
            },
        )
        if p2:
            print("  follow-up text:", repr(_text(p2)[:160]))
    elif p:
        print("  no function_call in output; text:", repr(_text(p)[:160]))


if __name__ == "__main__":
    main()
