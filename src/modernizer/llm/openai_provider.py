"""Adapter OpenAI com response_format=json_schema para structured output."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from openai import AsyncOpenAI

from modernizer.llm.base import LLMResult
from modernizer.llm.pricing import estimate_cost

logger = logging.getLogger(__name__)


class OpenAIProvider:
    name = "openai"

    def __init__(self, api_key: str | None, model: str) -> None:
        if not api_key:
            raise ValueError("OPENAI_API_KEY não configurada")
        self._client = AsyncOpenAI(api_key=api_key)
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
        started = time.perf_counter()
        response = await self._client.chat.completions.create(
            model=self._model,
            temperature=temperature,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "modernization_output",
                    "schema": json_schema,
                    "strict": True,
                },
            },
        )
        latency_ms = int((time.perf_counter() - started) * 1000)
        content_text = response.choices[0].message.content or ""
        parsed: dict[str, Any] | None = None
        try:
            parsed = json.loads(content_text)
        except json.JSONDecodeError:
            logger.warning("OpenAI retornou conteúdo não-JSON; mantendo texto puro")

        usage = response.usage
        input_tokens = getattr(usage, "prompt_tokens", 0) if usage else 0
        output_tokens = getattr(usage, "completion_tokens", 0) if usage else 0
        cost = estimate_cost(self._model, input_tokens, output_tokens)
        return LLMResult(
            content=content_text,
            parsed=parsed,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
            latency_ms=latency_ms,
            model=self._model,
            provider=self.name,
            raw={"finish_reason": response.choices[0].finish_reason},
        )
