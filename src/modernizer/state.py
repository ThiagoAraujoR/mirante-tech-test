"""Estado tipado compartilhado entre os nós do grafo."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, TypedDict


@dataclass
class ParsedSQL:
    """Saída do nó parser."""

    raw_source: str
    object_kind: Literal["function", "procedure", "unknown"] = "unknown"
    object_name: str = ""
    parameters: list[dict[str, Any]] = field(default_factory=list)
    return_type: str | None = None
    language: str = "plpgsql"
    sql_ast: list[dict[str, Any]] = field(default_factory=list)
    plpgsql_ast: list[dict[str, Any]] = field(default_factory=list)
    parser_used: str = "pglast"
    degraded: bool = False
    parse_error: str | None = None


@dataclass
class SemanticReport:
    """Saída do nó analyzer."""

    parameters: list[dict[str, Any]] = field(default_factory=list)
    declared_vars: list[dict[str, Any]] = field(default_factory=list)
    constructs: list[str] = field(default_factory=list)
    risks: list[dict[str, Any]] = field(default_factory=list)
    strategy_hints: dict[str, str] = field(default_factory=dict)
    referenced_tables: list[str] = field(default_factory=list)
    called_functions: list[str] = field(default_factory=list)


@dataclass
class ValidationReport:
    """Saída do nó validator."""

    static_ok: bool = False
    dynamic_ok: bool | None = None  # None = não executado
    syntax_errors: list[str] = field(default_factory=list)
    lint_warnings: list[str] = field(default_factory=list)
    dynamic_mismatches: list[str] = field(default_factory=list)
    dynamic_error: str | None = None


class ModernizerState(TypedDict, total=False):
    """Estado completo do grafo LangGraph."""

    # Inputs
    source_code: str
    schema_context: str | None
    llm_provider_override: str | None
    llm_model_override: str | None

    # Outputs incrementais por nó
    parsed: ParsedSQL
    semantic: SemanticReport
    generated_code: str
    generation_meta: dict[str, Any]
    validation: ValidationReport

    # Controle do grafo
    attempts: int
    previous_errors: list[str]

    # Final
    status: Literal["success", "failure", "partial", "pending"]
    error_message: str | None
    report: dict[str, Any]
    run_id: str | None
