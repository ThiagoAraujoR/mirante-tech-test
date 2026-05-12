"""Adapter Anthropic com tool_use para structured output e prompt caching."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from anthropic import AsyncAnthropic

from modernizer.llm.base import LLMResult
from modernizer.llm.pricing import estimate_cost

logger = logging.getLogger(__name__)


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, api_key: str | None, model: str) -> None:
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY não configurada")
        self._client = AsyncAnthropic(api_key=api_key)
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
        tool_name = "emit_modernization"
        tools = [
            {
                "name": tool_name,
                "description": (
                    "Emite o resultado da modernização SQL→Python "
                    "conforme o JSON schema fornecido."
                ),
                "input_schema": json_schema,
            }
        ]
        started = time.perf_counter()
        # System como bloco com cache_control para reduzir custo nas retries.
        system_blocks = [
            {
                "type": "text",
                "text": system,
                "cache_control": {"type": "ephemeral"},
            }
        ]
        # mypy não reconhece TypedDicts inline contra os overloads estritos do SDK
        # (system_blocks/tools/tool_choice/messages são dicts literais válidos em runtime).
        response = await self._client.messages.create(  # type: ignore[call-overload]
            model=self._model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system_blocks,
            tools=tools,
            tool_choice={"type": "tool", "name": tool_name},
            messages=[{"role": "user", "content": user}],
        )
        latency_ms = int((time.perf_counter() - started) * 1000)

        parsed: dict[str, Any] | None = None
        content_text = ""
        for block in response.content:
            if block.type == "tool_use" and block.name == tool_name:
                parsed = dict(block.input)
                content_text = json.dumps(parsed, ensure_ascii=False)
                break

        if parsed is None:
            # Fallback: junta texto bruto
            content_text = "".join(
                getattr(b, "text", "") for b in response.content if getattr(b, "type", "") == "text"
            )

        usage = response.usage
        input_tokens = getattr(usage, "input_tokens", 0) + getattr(
            usage, "cache_read_input_tokens", 0
        )
        output_tokens = getattr(usage, "output_tokens", 0)
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
            raw={"stop_reason": response.stop_reason},
        )
