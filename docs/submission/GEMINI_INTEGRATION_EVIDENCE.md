# Gemini Integration Evidence: Foresight-AI

**Project:** Foresight-AI — Industrial Operations Copilot & Deterministic Future Arena  
**Hackathon Track:** Berkeley x DeepMind Hackathon Online Track  
**Official SDK:** `google-genai==3.3.0`  
**Primary Model:** `gemini-3.8-flash`  
**Implementation Source File:** [`packages/foresight/src/foresight/agents/gemini.py`](file:///E:/Hackathons/foresight-ai/packages/foresight/src/foresight/agents/gemini.py)  

---

## 1. Executive Summary & Design Principles

Foresight-AI integrates **Google Gemini 3.8 Flash** as an intelligent Industrial Operations Copilot. In high-consequence physical systems (such as a 15 kW TEFC induction motor running critical material handling), generative models cannot be allowed unconstrained hallucination or direct actuator control.

Our integration adheres to six architectural principles:
1. **Official SDK Standards**: Built on the new `google-genai` Python SDK v3.3.0 (`from google import genai; from google.genai import types`).
2. **Schema-Strict Typed Function Calling**: Gemini cannot execute freeform shell commands or invent parameters. It is bounded to six deterministic, typed tools.
3. **Multi-Turn Stateful Dialogue**: Maintains conversation context with complete tool call request-response pairs using `types.Content`.
4. **Independent Physical Verification**: Gemini proposes candidate interventions; the deterministic digital twin simulates them; Verifier v5 audits them; and the human operator approves them.
5. **Server-Side Credential Isolation**: No API keys or tokens are ever sent to or stored in the client browser.
6. **Zero Disguised Fallbacks**: If the Gemini API is unreachable or unconfigured, the system falls back to a deterministic planner, clearly tagged in all audit trails and UI indicators.

---

## 2. Architecture & SDK Implementation

### 2.1 The Gemini Model Client (`foresight.agents.gemini`)

The core bridge is implemented in `GeminiModelClient`, conforming to Foresight's asynchronous LLM interface:

```python
# packages/foresight/src/foresight/agents/gemini.py
from google import genai
from google.genai import types

class GeminiModelClient:
    """Gemini client using the official google-genai SDK v3.3.0."""

    def __init__(self, settings: Settings, client: genai.Client | None = None) -> None:
        self._settings = settings
        self.provider = "gemini"
        self.model = settings.gemini_model  # defaults to "gemini-3.8-flash"
        self._conversations: dict[str, list[types.Content]] = {}
        
        if client is not None:
            self._client = client
        elif settings.provider("gemini-3.8-flash").configured:
            api_key = settings.gemini_api_key.get_secret_value()
            self._client = genai.Client(api_key=api_key)
        else:
            self._client = None
```

### 2.2 Dynamic Schema & Type Conversion

Tools in Foresight are defined via typed schemas. `_convert_to_gemini_type` dynamically maps standard JSON schema primitive types to Gemini's `types.Type` enums:

```python
def _convert_to_gemini_type(prop_type: str) -> types.Type:
    mapping = {
        "string": types.Type.STRING,
        "integer": types.Type.INTEGER,
        "number": types.Type.NUMBER,
        "boolean": types.Type.BOOLEAN,
        "array": types.Type.ARRAY,
        "object": types.Type.OBJECT,
    }
    return mapping.get(prop_type, types.Type.STRING)
```

Each tool declaration is assembled into a `types.Tool` bundle:
* `get_machine_state`: Retrieves frozen telemetry snapshot (speed, temperature, vibration, load).
* `get_sensor_history`: Fetches high-frequency rolling window time-series.
* `analyze_anomalies`: Calculates Isolation Forest outlier scores and CUSUM change-points.
* `predict_failure_risk`: Invokes isotonic-calibrated gradient-boosted risk models across 15m, 30m, and 60m horizons.
* `compare_futures`: Executes Common Random Number (CRN) digital-twin simulations comparing operational interventions.
* `verify_intervention`: Runs the candidate action through independent Verifier v5 physics gates.

---

## 3. Stateful Multi-Turn Conversation Management

To maintain coherence across multi-step diagnosis (Observe → Analyze → Hypothesize → Simulate → Verify → Recommend), `GeminiModelClient` tracks conversation state via `types.Content`:

1. **User / System Context**: Initiates session context with system prompts and frozen snapshot telemetry.
2. **Function Calling**: When Gemini returns a `function_call` part, it is packaged into `LLMResponse(tool_calls=[...])`.
3. **Tool Execution Return**: The local deterministic tool executes, and its output is returned to Gemini via `types.Part.from_function_response(name=..., response={"result": ...})`.
4. **State Storage**: The turn history is stored under `self._conversations[previous_response_id]`, ensuring seamless multi-turn reasoning without context loss.

```python
# Multi-turn response handling in GeminiModelClient:
if candidate.content:
    full_contents = list(contents)
    full_contents.append(candidate.content)
    self._conversations[resp_id] = full_contents

# Follow-up tool return:
followup_contents = list(self._conversations[previous_response_id])
tool_parts = [
    types.Part.from_function_response(
        name=tc.name,
        response={"result": tc.output},
    )
    for tc in tool_call_outputs
]
followup_contents.append(types.Content(role="user", parts=tool_parts))
```

---

## 4. Bounded Safety & Zero Fabrication

Industrial AI cannot fabricate data. In Foresight-AI:
* **LLMs Cannot Synthesize Telemetry**: The agent cannot invent temperature readings; `get_sensor_history` returns actual floats computed by the ODE solver.
* **LLMs Cannot Bypass Verification**: Gemini's `submit_recommendation` does not actuate equipment. It submits a proposal to **Verifier v5**.
* **Independent Physics Gate**: Verifier v5 re-simulates the proposal on 32 independent Monte Carlo seeds with an offset of +900,000. Even if Gemini claims an intervention is safe, Verifier v5 checks:
  1. Stator winding temperature $\le 140$ °C (safety margin on Class F 155 °C).
  2. ISO 10816-3 RMS vibration velocity $\le 6.1$ mm/s (margin on 7.1 mm/s trip).
  3. Action parameter validity and scheduling before simulated time-to-failure.

---

## 5. Token Usage & Economic Accounting

Gemini 3.8 Flash token usage is tracked per request and billed according to Google's official pricing structure:
* **Input Tokens**: $0.10 per 1,000,000 tokens ($0.00000010 / token).
* **Cached Input Tokens**: $0.025 per 1,000,000 tokens ($0.000000025 / token).
* **Output Tokens**: $0.40 per 1,000,000 tokens ($0.00000040 / token).

```python
# packages/foresight/src/foresight/config.py
# ProviderConfig registered for Google Gemini 3.8 Flash
price_input_per_m = 0.10
price_cached_input_per_m = 0.025
price_output_per_m = 0.40
```

Every response returns exact token counts (`input_tokens`, `output_tokens`) and cumulative session cost, ensuring plant engineers have complete financial visibility into AI operational overhead.

---

## 6. Transparent Fallback Behavior

When `GEMINI_API_KEY` is omitted, network drops, or quota is exhausted, Foresight-AI executes a clean fallback without disguising output:
1. `GeminiModelClient` raises `LLMError("Gemini client is not configured...")` or handles API exceptions gracefully.
2. The `AgentOrchestrator` catches the error and transitions to the `DeterministicPlanner`.
3. The response payload explicitly sets:
   ```json
   {
     "provider": "deterministic-planner",
     "selected_by": "optimizer_fallback",
     "notice": "Autonomous reasoning was performed by deterministic physics planner; not from a live Gemini model."
   }
   ```
4. In the UI, a amber banner informs the operator that deterministic fallback logic is running, preserving trust and audit compliance.

---

## 7. Verification Test Suite

The Gemini integration is covered by unit and integration tests in the test suite:

| Test File | Test Case | Target Verified |
|:---|:---|:---|
| `tests/unit/test_gemini_copilot.py` | `test_schema_type_conversion` | Accurate mapping of string, number, array, and object types to `google.genai.types.Type`. |
| `tests/unit/test_gemini_copilot.py` | `test_build_gemini_tools` | Creation of `types.Tool` with function declarations for all 6 operational tools. |
| `tests/unit/test_gemini_copilot.py` | `test_unconfigured_client_raises_llmerror` | Strict exception when API key is missing. |
| `tests/unit/test_gemini_copilot.py` | `test_gemini_client_create_response_text` | Direct text generation and token usage calculation. |
| `tests/unit/test_gemini_copilot.py` | `test_gemini_client_create_response_function_call` | Structured tool calling with Pydantic argument parsing. |
| `tests/unit/test_gemini_copilot.py` | `test_gemini_client_error_handling_graceful` | Error handling and graceful fallback on API errors. |
| `tests/integration/test_gemini_endpoints.py` | `test_future_arena_endpoint` | 3-way simulation endpoint execution with reproducibility. |
| `tests/integration/test_gemini_endpoints.py` | `test_safety_challenge_catalog_and_execution` | Adversarial injection and rejection by Verifier v5. |
| `tests/integration/test_gemini_endpoints.py` | `test_decision_receipt_generation_and_verification` | SHA-256 canonical hashing and tamper detection. |
| `tests/integration/test_gemini_endpoints.py` | `test_multimodal_gallery_and_analysis` | Multimodal inspection analysis and magic byte validation. |
| `tests/integration/test_gemini_endpoints.py` | `test_live_gemini_client_e2e` | Live end-to-end call against Google Gemini 3.8 Flash (executes when valid `AIzaSy...` key is set). |
