"""Adapter Google Gemini com response_schema para structured output.

Usa o SDK `google-genai` (novo, unificado). O Gemini aceita um subset de JSON
Schema (OpenAPI 3.0); fazemos a sanitização aqui para campos não suportados.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from modernizer.llm.base import LLMResult
from modernizer.llm.pricing import estimate_cost

logger = logging.getLogger(__name__)


def _sanitize_schema_for_gemini(schema: dict[str, Any]) -> dict[str, Any]:
    """Remove campos não suportados pelo schema do Gemini.

    Gemini aceita um subset do JSON Schema; campos como `additionalProperties`,
    `$schema`, `examples`, `default`, `title` e tipos `null` em unions são
    removidos para evitar erros do tipo `INVALID_ARGUMENT`.
    """

    if not isinstance(schema, dict):
        return schema

    unsupported = {"additionalProperties", "$schema", "examples", "default", "title", "$id"}
    clean: dict[str, Any] = {}
    for key, value in schema.items():
        if key in unsupported:
            continue
        if isinstance(value, dict):
            clean[key] = _sanitize_schema_for_gemini(value)
        elif isinstance(value, list):
            clean[key] = [
                _sanitize_schema_for_gemini(v) if isinstance(v, dict) else v for v in value
            ]
        else:
            clean[key] = value
    return clean


class GeminiProvider:
    name = "gemini"

    def __init__(self, api_key: str | None, model: str) -> None:
        if not api_key:
            raise ValueError("GOOGLE_API_KEY não configurada")

        # Import lazy: a dependência só é exigida se o provider for usado.
        from google import genai

        self._client = genai.Client(api_key=api_key)
        self._model = model

    async def generate_structured(
        self,
        *,
        system: str,
        user: str,
        json_schema: dict[str, Any],
        temperature: float = 0.0,
        max_tokens: int = 8192,
    ) -> LLMResult:
        from google.genai import types

        sanitized_schema = _sanitize_schema_for_gemini(json_schema)

        config = types.GenerateContentConfig(
            system_instruction=system,
            temperature=temperature,
            max_output_tokens=max_tokens,
            response_mime_type="application/json",
            response_schema=sanitized_schema,
        )

        started = time.perf_counter()
        response = await self._client.aio.models.generate_content(
            model=self._model,
            contents=user,
            config=config,
        )
        latency_ms = int((time.perf_counter() - started) * 1000)

        content_text = response.text or ""
        parsed: dict[str, Any] | None = None
        try:
            parsed = json.loads(content_text) if content_text else None
        except json.JSONDecodeError:
            logger.warning("Gemini retornou conteúdo não-JSON; mantendo texto puro")

        usage = getattr(response, "usage_metadata", None)
        input_tokens = getattr(usage, "prompt_token_count", 0) if usage else 0
        output_tokens = getattr(usage, "candidates_token_count", 0) if usage else 0
        cost = estimate_cost(self._model, input_tokens, output_tokens)

        finish_reason = None
        candidates = getattr(response, "candidates", None) or []
        if candidates:
            finish_reason = getattr(candidates[0], "finish_reason", None)
            finish_reason = str(finish_reason) if finish_reason is not None else None

        return LLMResult(
            content=content_text,
            parsed=parsed,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
            latency_ms=latency_ms,
            model=self._model,
            provider=self.name,
            raw={"finish_reason": finish_reason},
        )
