"""Environment-validated configuration. Secrets never leave the backend."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ProviderName = Literal["meta", "fireworks"]
PROVIDERS: tuple[ProviderName, ...] = ("meta", "fireworks")
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

    llm_provider: ProviderName = Field("meta", alias="FORESIGHT_LLM_PROVIDER")

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

    def provider(self, name: ProviderName | None = None) -> ProviderConfig:
        name = name or self.llm_provider
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
                # Muse Spark Open always reasons; "minimal" is not documented for it.
                efforts=("low", "medium", "high", "xhigh"),
            )
        raise ValueError(f"Unknown provider {name!r}")

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
