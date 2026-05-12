"""Nó de geração — chama o LLM com prompt construído a partir da AST e análise."""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any

from modernizer.config import get_settings
from modernizer.llm.factory import get_provider
from modernizer.llm.prompts import OUTPUT_SCHEMA, SYSTEM_PROMPT, build_user_prompt
from modernizer.state import ModernizerState, ParsedSQL

logger = logging.getLogger(__name__)


def _trim_ast(parsed: ParsedSQL, max_chars: int = 6000) -> dict[str, Any]:
    """Resume a AST para não estourar o prompt."""
    body_kinds: list[dict[str, Any]] = []

    def walk(stmts: list[dict[str, Any]], depth: int = 0) -> None:
        for s in stmts:
            entry = {"kind": s.get("kind"), "depth": depth}
            body_kinds.append(entry)
            walk(s.get("children", []) or [], depth + 1)

    for fn in parsed.plpgsql_ast or []:
        walk(fn.get("statements", []) or [])

    summary: dict[str, Any] = {
        "object_kind": parsed.object_kind,
        "object_name": parsed.object_name,
        "parameters": parsed.parameters,
        "return_type": parsed.return_type,
        "body_statement_kinds": body_kinds,
        "parser_used": parsed.parser_used,
        "degraded": parsed.degraded,
    }
    return summary


async def generate_node(state: ModernizerState) -> dict[str, Any]:
    settings = get_settings()
    source = state.get("source_code", "")
    parsed = state.get("parsed")
    semantic = state.get("semantic")
    schema_context = state.get("schema_context")
    previous_errors = state.get("previous_errors") or []

    if parsed is None or semantic is None:
        return {
            "status": "failure",
            "error_message": "generator: estado incompleto (parsed/semantic ausentes)",
        }

    parsed_summary = _trim_ast(parsed)
    semantic_dict = asdict(semantic)

    user_prompt = build_user_prompt(
        source_code=source,
        schema_context=schema_context,
        parsed_summary=parsed_summary,
        semantic_report=semantic_dict,
        previous_errors=previous_errors,
    )

    provider_name = state.get("llm_provider_override") or settings.llm_provider
    model = state.get("llm_model_override") or settings.llm_model

    try:
        provider = get_provider(provider_name, model)
    except Exception as exc:  # noqa: BLE001
        logger.error("falha ao instanciar provider: %s", exc)
        return {
            "status": "failure",
            "error_message": f"provider error: {exc}",
        }

    try:
        result = await provider.generate_structured(
            system=SYSTEM_PROMPT,
            user=user_prompt,
            json_schema=OUTPUT_SCHEMA,
            temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_tokens,
        )
    except Exception as exc:
        logger.exception("LLM falhou")
        return {
            "status": "failure",
            "error_message": f"llm error: {exc}",
        }

    parsed_out = result.parsed or {}
    generated_code = parsed_out.get("generated_code", "")
    if not generated_code.strip():
        return {
            "status": "failure",
            "error_message": "LLM retornou generated_code vazio",
            "generation_meta": {
                "provider": result.provider,
                "model": result.model,
                "latency_ms": result.latency_ms,
                "cost_usd": result.cost_usd,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
            },
        }

    generation_meta = {
        "provider": result.provider,
        "model": result.model,
        "latency_ms": result.latency_ms,
        "cost_usd": result.cost_usd,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "decisions": parsed_out.get("decisions", []),
        "caveats": parsed_out.get("caveats", []),
        "imports": parsed_out.get("imports", []),
    }

    attempts = (state.get("attempts") or 0) + 1
    logger.info(
        "generator: provider=%s model=%s tokens(in/out)=%d/%d cost=$%.4f attempt=%d",
        result.provider,
        result.model,
        result.input_tokens,
        result.output_tokens,
        result.cost_usd,
        attempts,
    )
    return {
        "generated_code": generated_code,
        "generation_meta": generation_meta,
        "attempts": attempts,
    }
