"""Definição e compilação do grafo LangGraph da pipeline de modernização."""

from __future__ import annotations

import logging
from typing import Any

from langgraph.graph import END, START, StateGraph

from modernizer.config import get_settings
from modernizer.nodes import (
    analyze_node,
    generate_node,
    parse_node,
    persist_node,
    validate_node,
)
from modernizer.state import ModernizerState, ValidationReport

logger = logging.getLogger(__name__)


def _after_parse(state: ModernizerState) -> str:
    """Se parse falhou completamente, pula direto para persist."""
    if state.get("status") == "failure":
        return "persist"
    parsed = state.get("parsed")
    if parsed is None or parsed.parse_error:
        return "persist"
    return "analyze"


def _after_generate(state: ModernizerState) -> str:
    if state.get("status") == "failure":
        return "persist"
    return "validate"


def _after_validate(state: ModernizerState) -> str:
    """Retry condicional: se estática falhou e ainda há tentativas, volta ao generate."""
    settings = get_settings()
    validation: ValidationReport | None = state.get("validation")
    attempts = state.get("attempts", 0)

    if validation is None:
        return "persist"

    if not validation.static_ok and attempts < settings.max_generate_attempts:
        # Anexa erros para a próxima tentativa
        previous_errors = list(state.get("previous_errors", []))
        previous_errors.extend(validation.syntax_errors)
        # `_set_retry` é um nó virtual implementado abaixo
        return "set_retry"

    return "persist"


async def _set_retry_node(state: ModernizerState) -> dict[str, Any]:
    """Pequeno nó utilitário que injeta previous_errors antes de regerar."""
    validation: ValidationReport | None = state.get("validation")
    previous_errors = list(state.get("previous_errors", []))
    if validation:
        previous_errors.extend(validation.syntax_errors)
    return {"previous_errors": previous_errors}


def build_graph() -> Any:
    workflow: StateGraph = StateGraph(ModernizerState)

    workflow.add_node("parse", parse_node)
    workflow.add_node("analyze", analyze_node)
    workflow.add_node("generate", generate_node)
    workflow.add_node("validate", validate_node)
    workflow.add_node("set_retry", _set_retry_node)
    workflow.add_node("persist", persist_node)

    workflow.add_edge(START, "parse")
    workflow.add_conditional_edges(
        "parse", _after_parse, {"analyze": "analyze", "persist": "persist"}
    )
    workflow.add_edge("analyze", "generate")
    workflow.add_conditional_edges(
        "generate", _after_generate, {"validate": "validate", "persist": "persist"}
    )
    workflow.add_conditional_edges(
        "validate",
        _after_validate,
        {"set_retry": "set_retry", "persist": "persist"},
    )
    workflow.add_edge("set_retry", "generate")
    workflow.add_edge("persist", END)

    return workflow.compile()


# Exportado para o langgraph cli (referência em langgraph.json).
graph = build_graph()
