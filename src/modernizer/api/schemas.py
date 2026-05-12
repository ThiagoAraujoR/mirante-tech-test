"""Schemas pydantic para request/response da API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ModernizeRequest(BaseModel):
    # Pydantic v2: aceita "schema" no JSON (alias) mas o atributo Python é db_schema
    # para não colidir com BaseModel.schema (método legacy do v1).
    model_config = ConfigDict(populate_by_name=True)

    source_code: str = Field(..., min_length=1, description="Stored procedure PL/pgSQL")
    db_schema: str | None = Field(
        default=None,
        alias="schema",
        description="Schema do banco legado (Anexo A) como contexto opcional",
    )
    llm_provider: Literal["anthropic", "openai", "gemini"] | None = None
    llm_model: str | None = None


class ModernizeResponse(BaseModel):
    run_id: str | None
    status: Literal["success", "failure", "partial"]
    generated_code: str | None
    report: dict[str, Any]
    error_message: str | None = None


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    db: Literal["ok", "down"]
    llm: str
    langfuse: Literal["enabled", "disabled"]
    version: str
