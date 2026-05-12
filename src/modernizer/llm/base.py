"""Interface comum aos provedores de LLM."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class LLMResult:
    """Resultado de uma chamada LLM, normalizado entre provedores."""

    content: str
    """Conteúdo textual ou JSON serializado retornado pelo modelo."""

    parsed: dict[str, Any] | None = None
    """Conteúdo já decodificado se o provider devolver structured output."""

    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0
    model: str = ""
    provider: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


class LLMProvider(Protocol):
    name: str

    async def generate_structured(
        self,
        *,
        system: str,
        user: str,
        json_schema: dict[str, Any],
        temperature: float = 0.0,
        max_tokens: int = 8192,
    ) -> LLMResult:
        """Gera saída estruturada conforme `json_schema`.

        Retorna sempre um `LLMResult` com `parsed` preenchido quando bem-sucedido.
        Levanta exceção em caso de falha definitiva.
        """
        ...
