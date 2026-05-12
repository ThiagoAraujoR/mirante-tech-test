"""Configurações da aplicação carregadas via env vars."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---------------- LLM ----------------
    llm_provider: Literal["anthropic", "openai", "gemini"] = "anthropic"
    llm_model: str = "claude-sonnet-4-5-20250929"
    llm_temperature: float = 0.0
    llm_max_tokens: int = 8192

    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    google_api_key: str | None = None

    # ---------------- DB ----------------
    database_url: str = Field(
        default="postgresql+asyncpg://mirante:mirante@localhost:5432/mirante",
        description="URL async do banco principal (modernization_history)",
    )
    sandbox_database_url: str = Field(
        default="postgresql+psycopg://sandbox:sandbox@localhost:5433/sandbox",
        description="URL sync do banco sandbox (validação dinâmica)",
    )

    # ---------------- Langfuse ----------------
    langfuse_enabled: bool = False
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    langfuse_host: str = "http://localhost:3000"

    # ---------------- Pipeline ----------------
    max_generate_attempts: int = 2
    enable_dynamic_validation: bool = True
    results_dir: str = Field(
        default="results",
        description="Diretório onde o código Python gerado é materializado a cada run.",
    )
    write_results_to_disk: bool = True


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
