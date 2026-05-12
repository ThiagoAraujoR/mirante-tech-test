"""Nó de análise semântica — derivado da AST do pglast + regex sobre o source.

Implementação determinística (sem LLM) que produz risk markers e strategy hints
para alimentar o prompt do generator.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from modernizer.state import ModernizerState, ParsedSQL, SemanticReport

logger = logging.getLogger(__name__)

# Mapeamento SQL → Python para sugestão de tipos.
SQL_TO_PY = {
    "bigint": "int",
    "integer": "int",
    "int": "int",
    "smallint": "int",
    "int4": "int",
    "int8": "int",
    "numeric": "Decimal",
    "decimal": "Decimal",
    "real": "float",
    "double precision": "float",
    "text": "str",
    "varchar": "str",
    "char": "str",
    "boolean": "bool",
    "bool": "bool",
    "date": "date",
    "timestamp": "datetime",
    "timestamptz": "datetime",
    "jsonb": "dict[str, Any]",
    "json": "dict[str, Any]",
    "uuid": "UUID",
}


def _suggest_py_type(sql_type: str | None) -> str:
    if not sql_type:
        return "Any"
    low = sql_type.lower().split("(")[0].strip()
    return SQL_TO_PY.get(low, "Any")


# Construções de risco detectáveis por regex no source.
RISK_PATTERNS: list[tuple[str, str, str]] = [
    (
        r"\bCURSOR\b\s+FOR",
        "explicit_cursor",
        "Cursor explícito — preferir SQL set-based ou fetch em lote no Python.",
    ),
    (
        r"FOR\s+UPDATE\b",
        "row_lock",
        "Bloqueio de linha — manter SELECT FOR UPDATE no SQL para preservar semântica.",
    ),
    (
        r"RAISE\s+(EXCEPTION|NOTICE|WARNING)\b",
        "raise_stmt",
        "RAISE — mapear EXCEPTION para classe Python; NOTICE/WARNING para logging.",
    ),
    (
        r"WITH\s+RECURSIVE\b",
        "recursive_cte",
        "CTE recursiva — manter como SQL bruto, mais simples e eficiente.",
    ),
    (
        r"\bRETURN\s+QUERY\b",
        "return_setof",
        "RETURN QUERY (SETOF) — função deve retornar list[dict].",
    ),
    (
        r"GET\s+DIAGNOSTICS\b",
        "get_diagnostics",
        "GET DIAGNOSTICS ROW_COUNT — usar result.rowcount.",
    ),
    (
        r"\bEXCEPTION\b\s+WHEN\b",
        "exception_block",
        "Bloco EXCEPTION — mapear para try/except com logging de auditoria.",
    ),
    (
        r"\bJSONB\b|jsonb_build_object",
        "jsonb",
        "Manipulação JSONB — usar dict Python ou função do SGBD via texto SQL.",
    ),
    (
        r"\bFOR\s+\w+\s+IN\b",
        "for_loop",
        "FOR loop iterando sobre query — considerar SQL set-based.",
    ),
    (
        r"\bPERFORM\b",
        "perform",
        "PERFORM — descarta resultado, traduz para session.execute(text(...)).",
    ),
]


def _detect_risks(source: str) -> list[dict[str, Any]]:
    risks: list[dict[str, Any]] = []
    for pat, tag, advice in RISK_PATTERNS:
        if re.search(pat, source, re.IGNORECASE):
            risks.append({"tag": tag, "advice": advice})
    return risks


def _detect_constructs(plpgsql_ast: list[dict[str, Any]]) -> list[str]:
    """Coleta os tipos de statement encontrados no corpo."""
    found: set[str] = set()

    def walk(stmts: list[dict[str, Any]]) -> None:
        for s in stmts or []:
            kind = s.get("kind")
            if kind:
                found.add(kind)
            walk(s.get("children", []) or [])

    for fn in plpgsql_ast or []:
        walk(fn.get("statements", []) or [])
    return sorted(found)


def _detect_tables(source: str) -> list[str]:
    """Encontra nomes de tabelas referenciadas (best-effort regex)."""
    matches = re.findall(
        r"\b(?:FROM|JOIN|UPDATE|INTO)\s+([\w\.]+)", source, re.IGNORECASE
    )
    tables = {m.lower() for m in matches if not m.lower().startswith("(")}
    return sorted(tables)


def _detect_called_functions(source: str) -> list[str]:
    """Funções referenciadas no body (fn_xxx, sp_xxx)."""
    matches = re.findall(r"\b(fn_\w+|sp_\w+)\s*\(", source, re.IGNORECASE)
    # Remove a própria função detectada do parsed.
    return sorted(set(m.lower() for m in matches))


def _build_strategy_hints(risks: list[dict[str, Any]]) -> dict[str, str]:
    """Para cada risco, recomenda estratégia de tradução."""
    hints: dict[str, str] = {
        "queries_simples": "keep_as_raw_sql",
        "controle_de_fluxo": "python_logic",
    }
    tags = {r["tag"] for r in risks}
    if "explicit_cursor" in tags:
        hints["cursor"] = "rewrite_as_set_based_sql_when_possible"
    if "row_lock" in tags:
        hints["row_lock"] = "keep_as_raw_sql_with_for_update"
    if "recursive_cte"  in tags:
        hints["recursive_cte"] = "keep_as_raw_sql"
    if "return_setof" in tags:
        hints["return_shape"] = "return_list_of_dict"
    if "exception_block" in tags:
        hints["error_handling"] = "try_except_with_audit_log"
    if "jsonb" in tags:
        hints["jsonb"] = "use_dict_in_python_serialize_to_jsonb"
    if "raise_stmt" in tags:
        hints["raise"] = "map_to_custom_exception_class"
    return hints


def analyze_node(state: ModernizerState) -> dict[str, Any]:
    parsed: ParsedSQL | None = state.get("parsed")
    if parsed is None or parsed.parse_error:
        return {
            "semantic": SemanticReport(
                risks=[{"tag": "no_ast", "advice": "Parser falhou; análise degradada."}],
            )
        }

    source = parsed.raw_source
    risks = _detect_risks(source)
    constructs = _detect_constructs(parsed.plpgsql_ast)
    tables = _detect_tables(source)
    called = _detect_called_functions(source)

    # Anota parâmetros com sugestão de tipo Python.
    annotated_params = []
    for p in parsed.parameters:
        annotated_params.append(
            {**p, "py_type": _suggest_py_type(p.get("type"))}
        )

    semantic = SemanticReport(
        parameters=annotated_params,
        constructs=constructs,
        risks=risks,
        strategy_hints=_build_strategy_hints(risks),
        referenced_tables=[t for t in tables if t not in {parsed.object_name.lower()}],
        called_functions=[c for c in called if c != parsed.object_name.lower()],
    )
    logger.info(
        "analyzer: object=%s constructs=%d risks=%d tables=%d",
        parsed.object_name,
        len(constructs),
        len(risks),
        len(tables),
    )
    return {"semantic": semantic}
