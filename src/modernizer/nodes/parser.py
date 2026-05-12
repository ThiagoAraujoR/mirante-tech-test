"""Nó de parsing — usa pglast (libpg_query) com fallback para sqlparse."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from modernizer.state import ModernizerState, ParsedSQL

logger = logging.getLogger(__name__)


def _summarize_create(stmt: dict[str, Any]) -> dict[str, Any]:
    """Extrai dados relevantes do nó CREATE FUNCTION/PROCEDURE do pglast."""

    create = stmt.get("CreateFunctionStmt") or {}
    is_proc = bool(create.get("is_procedure"))
    funcname_nodes = create.get("funcname") or []
    name = ".".join(
        n.get("String", {}).get("sval", "") for n in funcname_nodes if "String" in n
    ).strip(".")

    parameters: list[dict[str, Any]] = []
    for p in create.get("parameters") or []:
        param = p.get("FunctionParameter") or {}
        type_node = param.get("argType") or {}
        type_names = type_node.get("names") or []
        type_name = ".".join(
            n.get("String", {}).get("sval", "") for n in type_names if "String" in n
        ).strip(".")
        mode = param.get("mode", "FUNC_PARAM_DEFAULT")
        # Mapeamento simplificado
        mode_map = {
            "FUNC_PARAM_IN": "IN",
            "FUNC_PARAM_OUT": "OUT",
            "FUNC_PARAM_INOUT": "INOUT",
            "FUNC_PARAM_DEFAULT": "IN",
            "FUNC_PARAM_VARIADIC": "VARIADIC",
            "FUNC_PARAM_TABLE": "TABLE",
        }
        parameters.append(
            {
                "name": param.get("name"),
                "type": type_name,
                "mode": mode_map.get(mode, mode),
            }
        )

    return_type: str | None = None
    return_node = create.get("returnType")
    if return_node:
        rt_names = return_node.get("names") or []
        return_type = ".".join(
            n.get("String", {}).get("sval", "") for n in rt_names if "String" in n
        ).strip(".")
        if return_node.get("setof"):
            return_type = f"SETOF {return_type}"

    return {
        "kind": "procedure" if is_proc else "function",
        "name": name,
        "parameters": parameters,
        "return_type": return_type,
    }


def _shallow_plpgsql_summary(plpgsql_ast: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Resume os tipos de statement do corpo PL/pgSQL.

    Mantém leve para não estourar o prompt: só nomes de stmt e contadores.
    """

    summary: list[dict[str, Any]] = []
    for fn in plpgsql_ast or []:
        function = fn.get("PLpgSQL_function") or {}
        action = function.get("action") or {}
        block = action.get("PLpgSQL_stmt_block") or action
        stmts = block.get("body") or []
        summary.append(
            {
                "datums": [
                    next(iter(d.keys()))
                    for d in function.get("datums") or []
                    if isinstance(d, dict) and d
                ],
                "statements": _flatten_stmts(stmts),
            }
        )
    return summary


def _flatten_stmts(stmts: list[Any], depth: int = 0) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for s in stmts or []:
        if not isinstance(s, dict):
            continue
        for kind, body in s.items():
            entry: dict[str, Any] = {"kind": kind, "depth": depth}
            if isinstance(body, dict):
                # Coleta filhos comuns (then_body, else_body, body, exceptions)
                nested: list[dict[str, Any]] = []
                for child_key in ("body", "then_body", "else_body", "exceptions", "loop_body"):
                    child = body.get(child_key)
                    if isinstance(child, list):
                        nested.extend(_flatten_stmts(child, depth + 1))
                    elif isinstance(child, dict):
                        nested.extend(_flatten_stmts([child], depth + 1))
                if nested:
                    entry["children"] = nested
            out.append(entry)
    return out


def parse_with_pglast(source: str) -> ParsedSQL:
    import pglast
    import pglast.parser

    parsed = ParsedSQL(raw_source=source, parser_used="pglast")

    # pglast.parser.parse_sql_json devolve uma string JSON com a árvore completa
    # já em dicts puros (nodes pglast usam __slots__, não __dict__, então a
    # serialização manual via getattr/vars era inviável).
    try:
        sql_ast_json = pglast.parser.parse_sql_json(source)
    except Exception as exc:
        raise RuntimeError(f"pglast.parse_sql_json falhou: {exc}") from exc

    sql_ast_doc = json.loads(sql_ast_json)
    stmts = sql_ast_doc.get("stmts") or []
    parsed.sql_ast = stmts

    if stmts:
        # Estrutura: stmts[0] = {"stmt": {"CreateFunctionStmt": {...}}, ...}
        stmt = stmts[0].get("stmt", {}) if isinstance(stmts[0], dict) else {}
        summary = _summarize_create(stmt)
        parsed.object_kind = summary["kind"]
        parsed.object_name = summary["name"] or ""
        parsed.parameters = summary["parameters"]
        parsed.return_type = summary["return_type"]

    # AST do corpo PL/pgSQL (precisa de um CREATE FUNCTION/PROCEDURE válido).
    try:
        plpgsql_ast_raw = pglast.parse_plpgsql(source)
        parsed.plpgsql_ast = _shallow_plpgsql_summary(plpgsql_ast_raw)
    except Exception as exc:  # noqa: BLE001
        logger.warning("parse_plpgsql falhou (procede sem corpo): %s", exc)
        parsed.plpgsql_ast = []

    return parsed


def parse_with_sqlparse(source: str) -> ParsedSQL:
    """Fallback degradado: extrai assinatura via regex + sqlparse."""

    import sqlparse

    parsed = ParsedSQL(raw_source=source, parser_used="sqlparse", degraded=True)
    statements = sqlparse.parse(source)
    parsed.sql_ast = [{"tokens": [t.ttype.__class__.__name__ for t in s.tokens]} for s in statements]

    m = re.search(
        r"CREATE\s+OR\s+REPLACE\s+(FUNCTION|PROCEDURE)\s+([\w\.]+)\s*\(",
        source,
        re.IGNORECASE,
    )
    if m:
        parsed.object_kind = m.group(1).lower()  # type: ignore[assignment]
        parsed.object_name = m.group(2)

    return parsed


def parse_node(state: ModernizerState) -> dict[str, Any]:
    """Nó LangGraph: retorna apenas as chaves modificadas."""

    source = state.get("source_code", "")
    if not source.strip():
        return {
            "parsed": ParsedSQL(raw_source="", parse_error="source_code vazio", degraded=True),
            "status": "failure",
            "error_message": "source_code vazio",
        }

    try:
        parsed = parse_with_pglast(source)
        logger.info(
            "parser: %s '%s' (params=%d)",
            parsed.object_kind,
            parsed.object_name,
            len(parsed.parameters),
        )
        return {"parsed": parsed}
    except Exception as exc:  # noqa: BLE001
        logger.warning("pglast falhou, tentando fallback sqlparse: %s", exc)
        try:
            parsed = parse_with_sqlparse(source)
            parsed.parse_error = str(exc)
            return {"parsed": parsed}
        except Exception as exc2:  # noqa: BLE001
            logger.error("ambos os parsers falharam: %s", exc2)
            return {
                "parsed": ParsedSQL(
                    raw_source=source,
                    degraded=True,
                    parse_error=f"pglast: {exc} | sqlparse: {exc2}",
                ),
                "status": "failure",
                "error_message": f"parse failed: {exc2}",
            }
