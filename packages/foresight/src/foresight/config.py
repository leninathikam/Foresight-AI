"""Environment-validated configuration. Secrets never leave the backend."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ProviderName = Literal[
    "gemini-3.8-flash",
    "gemini-2.0-flash",
    "gemini-1.5-pro",
    "gemini-1.5-flash",
    "gemini-2.0-flash-lite",
    "gemini-2.5-flash",
    "gemini-2.5-pro",
    "gemini-2.5-flash-lite",
    "gemini",
    "meta",
    "fireworks",
]
PROVIDERS: tuple[ProviderName, ...] = (
    "gemini-3.8-flash",
    "gemini-2.0-flash",
    "gemini-1.5-pro",
    "gemini-1.5-flash",
    "gemini-2.0-flash-lite",
)
REASONING_EFFORTS = ("minimal", "low", "medium", "high", "xhigh")


@dataclass(frozen=True)
class ProviderConfig:
    """One OpenAI-Responses-compatible endpoint serving a Meta model."""

    name: ProviderName
    label: str
    trace_id: str
    base_url: str
    api_key: SecretStr | None
    model: str
    price_input_per_m: float
    price_cached_input_per_m: float
    price_output_per_m: float
    efforts: tuple[str, ...]

    @property
    def configured(self) -> bool:
        return self.api_key is not None and bool(self.api_key.get_secret_value().strip())

    def cost_usd(self, input_tokens: int, cached_input_tokens: int, output_tokens: int) -> float:
        cached = min(cached_input_tokens, input_tokens)
        return (
            (input_tokens - cached) / 1e6 * self.price_input_per_m
            + cached / 1e6 * self.price_cached_input_per_m
            + output_tokens / 1e6 * self.price_output_per_m
        )


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    llm_provider: ProviderName = Field("gemini-3.8-flash", alias="FORESIGHT_LLM_PROVIDER")

    # Gemini (Google GenAI SDK)
    gemini_api_key: SecretStr | None = Field(None, alias="GEMINI_API_KEY")
    google_api_key: SecretStr | None = Field(None, alias="GOOGLE_API_KEY")
    gemini_model: str = Field("gemini-3.8-flash", alias="FORESIGHT_GEMINI_MODEL")
    gemini_price_input_per_m: float = Field(0.10, alias="FORESIGHT_GEMINI_PRICE_INPUT_PER_M")
    gemini_price_cached_input_per_m: float = Field(
        0.025, alias="FORESIGHT_GEMINI_PRICE_CACHED_INPUT_PER_M"
    )
    gemini_price_output_per_m: float = Field(0.40, alias="FORESIGHT_GEMINI_PRICE_OUTPUT_PER_M")

    model_api_key: SecretStr | None = Field(None, alias="MODEL_API_KEY")
    meta_api_base_url: str = Field("https://api.meta.ai/v1", alias="META_API_BASE_URL")
    reasoning_model: str = Field("muse-spark-1.3", alias="FORESIGHT_REASONING_MODEL")

    fireworks_api_key: SecretStr | None = Field(None, alias="FIREWORKS_API_KEY")
    fireworks_base_url: str = Field(
        "https://api.fireworks.ai/inference/v1", alias="FIREWORKS_BASE_URL"
    )
    fireworks_model: str = Field(
        "accounts/fireworks/models/muse-spark-open", alias="FIREWORKS_MODEL"
    )

    reasoning_effort: str = Field("medium", alias="FORESIGHT_REASONING_EFFORT")
    llm_timeout_s: float = Field(90.0, alias="FORESIGHT_LLM_TIMEOUT_S", gt=0, le=600)
    llm_max_retries: int = Field(3, alias="FORESIGHT_LLM_MAX_RETRIES", ge=0, le=8)
    agent_max_tool_calls: int = Field(12, alias="FORESIGHT_AGENT_MAX_TOOL_CALLS", ge=1, le=40)
    agent_max_revisions: int = Field(2, alias="FORESIGHT_AGENT_MAX_REVISIONS", ge=0, le=5)
    agent_timeout_s: float = Field(300.0, alias="FORESIGHT_AGENT_TIMEOUT_S", gt=0)
    cors_origins: str = Field("http://localhost:3000", alias="FORESIGHT_CORS_ORIGINS")
    default_sim_speed: float = Field(60.0, alias="FORESIGHT_SIM_SPEED", gt=0, le=1000)
    alarm_prioritized_dispatch: bool = Field(True, alias="FORESIGHT_ALARM_PRIORITIZED_DISPATCH")
    expanded_candidate_grid: bool = Field(False, alias="FORESIGHT_EXPANDED_CANDIDATE_GRID")

    # Pre-allocation budget reservation limits (USD). None disables the ceiling.
    llm_total_budget_usd: float | None = Field(10.0, alias="FORESIGHT_TOTAL_BUDGET_USD")
    llm_session_budget_usd: float | None = Field(1.0, alias="FORESIGHT_SESSION_BUDGET_USD")

    # Published list prices (USD per 1M tokens) for cost accounting in traces. Meta's cached-input
    # price defaults to the full input price (conservative) unless set explicitly.
    price_input_per_m: float = Field(1.25, alias="FORESIGHT_PRICE_INPUT_PER_M")
    price_cached_input_per_m: float | None = Field(None, alias="FORESIGHT_PRICE_CACHED_INPUT_PER_M")
    price_output_per_m: float = Field(4.25, alias="FORESIGHT_PRICE_OUTPUT_PER_M")
    fireworks_price_input_per_m: float = Field(1.25, alias="FIREWORKS_PRICE_INPUT_PER_M")
    fireworks_price_cached_input_per_m: float = Field(
        0.15, alias="FIREWORKS_PRICE_CACHED_INPUT_PER_M"
    )
    fireworks_price_output_per_m: float = Field(4.25, alias="FIREWORKS_PRICE_OUTPUT_PER_M")

    @field_validator("reasoning_effort")
    @classmethod
    def _effort(cls, v: str) -> str:
        if v not in REASONING_EFFORTS:
            raise ValueError(f"FORESIGHT_REASONING_EFFORT must be one of {list(REASONING_EFFORTS)}")
        return v

    def _build_provider_config(self, name: str) -> ProviderConfig:
        key = self.gemini_api_key or self.google_api_key
        if name in ("gemini-3.8-flash", "gemini-2.5-flash", "gemini"):
            return ProviderConfig(
                name="gemini-3.8-flash",
                label="Google Gemini 3.8 Flash",
                trace_id="gemini",
                base_url="https://generativelanguage.googleapis.com",
                api_key=key,
                model="gemini-3.8-flash",
                price_input_per_m=0.10,
                price_cached_input_per_m=0.025,
                price_output_per_m=0.40,
                efforts=REASONING_EFFORTS,
            )
        if name in ("gemini-2.0-flash", "gemini-flash"):
            return ProviderConfig(
                name="gemini-2.0-flash",
                label="Google Gemini 2.0 Flash",
                trace_id="gemini-2.0-flash",
                base_url="https://generativelanguage.googleapis.com",
                api_key=key,
                model="gemini-2.0-flash",
                price_input_per_m=0.10,
                price_cached_input_per_m=0.025,
                price_output_per_m=0.40,
                efforts=REASONING_EFFORTS,
            )
        if name in ("gemini-1.5-pro", "gemini-2.5-pro", "gemini-pro"):
            return ProviderConfig(
                name="gemini-1.5-pro",
                label="Google Gemini 1.5 Pro",
                trace_id="gemini-1.5-pro",
                base_url="https://generativelanguage.googleapis.com",
                api_key=key,
                model="gemini-1.5-pro",
                price_input_per_m=1.25,
                price_cached_input_per_m=0.3125,
                price_output_per_m=5.00,
                efforts=REASONING_EFFORTS,
            )
        if name in ("gemini-1.5-flash", "gemini-flash"):
            return ProviderConfig(
                name="gemini-1.5-flash",
                label="Google Gemini 1.5 Flash",
                trace_id="gemini-1.5-flash",
                base_url="https://generativelanguage.googleapis.com",
                api_key=key,
                model="gemini-1.5-flash",
                price_input_per_m=0.075,
                price_cached_input_per_m=0.01875,
                price_output_per_m=0.30,
                efforts=REASONING_EFFORTS,
            )
        if name in ("gemini-2.0-flash-lite", "gemini-2.5-flash-lite", "gemini-flash-lite"):
            return ProviderConfig(
                name="gemini-2.0-flash-lite",
                label="Google Gemini 2.0 Flash-Lite",
                trace_id="gemini-2.0-flash-lite",
                base_url="https://generativelanguage.googleapis.com",
                api_key=key,
                model="gemini-2.0-flash-lite",
                price_input_per_m=0.075,
                price_cached_input_per_m=0.020,
                price_output_per_m=0.30,
                efforts=REASONING_EFFORTS,
            )
        if name == "meta":
            return ProviderConfig(
                name="meta",
                label="Meta Model API",
                trace_id="meta-model-api",
                base_url=self.meta_api_base_url,
                api_key=self.model_api_key,
                model=self.reasoning_model,
                price_input_per_m=self.price_input_per_m,
                price_cached_input_per_m=(
                    self.price_input_per_m
                    if self.price_cached_input_per_m is None
                    else self.price_cached_input_per_m
                ),
                price_output_per_m=self.price_output_per_m,
                efforts=REASONING_EFFORTS,
            )
        if name == "fireworks":
            return ProviderConfig(
                name="fireworks",
                label="Fireworks AI",
                trace_id="fireworks",
                base_url=self.fireworks_base_url,
                api_key=self.fireworks_api_key,
                model=self.fireworks_model,
                price_input_per_m=self.fireworks_price_input_per_m,
                price_cached_input_per_m=self.fireworks_price_cached_input_per_m,
                price_output_per_m=self.fireworks_price_output_per_m,
                efforts=("low", "medium", "high", "xhigh"),
            )
        raise ValueError(f"Unknown provider {name!r}")

    def provider(self, name: ProviderName | None = None) -> ProviderConfig:
        name = name or self.llm_provider
        return self._build_provider_config(name)

    @property
    def configured_providers(self) -> list[ProviderConfig]:
        return [p for p in (self.provider(n) for n in PROVIDERS) if p.configured]

    @property
    def llm_configured(self) -> bool:
        return self.provider().configured

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
