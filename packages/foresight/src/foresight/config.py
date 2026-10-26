"""Environment-validated configuration. Secrets never leave the backend."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    model_api_key: SecretStr | None = Field(None, alias="MODEL_API_KEY")
    meta_api_base_url: str = Field("https://api.meta.ai/v1", alias="META_API_BASE_URL")
    reasoning_model: str = Field("muse-spark-1.3", alias="FORESIGHT_REASONING_MODEL")
    reasoning_effort: str = Field("medium", alias="FORESIGHT_REASONING_EFFORT")
    llm_timeout_s: float = Field(90.0, alias="FORESIGHT_LLM_TIMEOUT_S", gt=0, le=600)
    llm_max_retries: int = Field(3, alias="FORESIGHT_LLM_MAX_RETRIES", ge=0, le=8)
    agent_max_tool_calls: int = Field(12, alias="FORESIGHT_AGENT_MAX_TOOL_CALLS", ge=1, le=40)
    agent_max_revisions: int = Field(2, alias="FORESIGHT_AGENT_MAX_REVISIONS", ge=0, le=5)
    agent_timeout_s: float = Field(300.0, alias="FORESIGHT_AGENT_TIMEOUT_S", gt=0)
    cors_origins: str = Field("http://localhost:3000", alias="FORESIGHT_CORS_ORIGINS")
    default_sim_speed: float = Field(60.0, alias="FORESIGHT_SIM_SPEED", gt=0, le=1000)

    # Published Model API list prices (USD per 1M tokens) for cost accounting in traces.
    price_input_per_m: float = Field(1.25, alias="FORESIGHT_PRICE_INPUT_PER_M")
    price_output_per_m: float = Field(4.25, alias="FORESIGHT_PRICE_OUTPUT_PER_M")

    @field_validator("reasoning_effort")
    @classmethod
    def _effort(cls, v: str) -> str:
        allowed = {"minimal", "low", "medium", "high", "xhigh"}
        if v not in allowed:
            raise ValueError(f"FORESIGHT_REASONING_EFFORT must be one of {sorted(allowed)}")
        return v

    @property
    def llm_configured(self) -> bool:
        return self.model_api_key is not None and bool(
            self.model_api_key.get_secret_value().strip()
        )

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
