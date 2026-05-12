"""Métricas de avaliação automática da qualidade da migração SQL→Python."""

from __future__ import annotations

import ast
import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class MetricResult:
    name: str
    value: float
    details: dict[str, Any]


def ast_parse_metric(generated_code: str) -> MetricResult:
    """1.0 se o código gerado passa em ast.parse, 0.0 caso contrário."""
    try:
        ast.parse(generated_code)
        return MetricResult("ast_parse_rate", 1.0, {"ok": True})
    except SyntaxError as exc:
        return MetricResult(
            "ast_parse_rate",
            0.0,
            {"ok": False, "error": f"line {exc.lineno}: {exc.msg}"},
        )


def structural_similarity_metric(
    sql_kinds: list[str], generated_code: str
) -> MetricResult:
    """Proxy de similaridade estrutural usando contagem de construções equivalentes.

    Para uma versão mais rigorosa, usaria tree-edit distance via APTED entre AST do
    PL/pgSQL e AST do Python. Aqui simplificamos: compara presença de construções-chave.
    """
    try:
        tree = ast.parse(generated_code)
    except SyntaxError:
        return MetricResult("structural_similarity", 0.0, {"ok": False})

    py_kinds: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.If):
            py_kinds.add("if")
        elif isinstance(node, (ast.For, ast.While)):
            py_kinds.add("loop")
        elif isinstance(node, ast.Try):
            py_kinds.add("exception")
        elif isinstance(node, ast.Raise):
            py_kinds.add("raise")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            py_kinds.add("function")
        elif isinstance(node, ast.Return):
            py_kinds.add("return")

    sql_lower = {k.lower() for k in sql_kinds}
    expected: set[str] = set()
    if any("if" in k for k in sql_lower):
        expected.add("if")
    if any("loop" in k or "fori" in k for k in sql_lower):
        expected.add("loop")
    if any("exception" in k for k in sql_lower):
        expected.add("exception")
    if any("raise" in k for k in sql_lower):
        expected.add("raise")
    expected.add("function")

    if not expected:
        return MetricResult("structural_similarity", 1.0, {"expected": [], "found": list(py_kinds)})

    matched = expected & py_kinds
    score = len(matched) / len(expected)
    return MetricResult(
        "structural_similarity",
        round(score, 4),
        {"expected": sorted(expected), "matched": sorted(matched), "py_kinds": sorted(py_kinds)},
    )


def exec_equivalence_from_report(report: dict[str, Any]) -> MetricResult:
    """Lê o resultado da validação dinâmica registrado no report."""
    validation = report.get("validation") or {}
    dyn_ok = validation.get("dynamic_ok")
    if dyn_ok is True:
        return MetricResult("exec_equivalence", 1.0, {"status": "match"})
    if dyn_ok is False:
        return MetricResult(
            "exec_equivalence",
            0.0,
            {"status": "mismatch", "details": validation.get("dynamic_mismatches", [])},
        )
    return MetricResult(
        "exec_equivalence",
        0.5,
        {"status": "not_executed", "reason": validation.get("dynamic_error")},
    )


async def llm_judge_metric(source_sql: str, generated_code: str) -> MetricResult:
    """Critic LLM com rubrica fixa (1-5 em quatro eixos)."""
    from modernizer.llm.factory import get_provider
    from modernizer.llm.prompts import (
        JUDGE_SCHEMA,
        JUDGE_SYSTEM_PROMPT,
        build_judge_user_prompt,
    )

    try:
        provider = get_provider()
        result = await provider.generate_structured(
            system=JUDGE_SYSTEM_PROMPT,
            user=build_judge_user_prompt(source_sql, generated_code),
            json_schema=JUDGE_SCHEMA,
            temperature=0,
            max_tokens=1024,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("llm_judge falhou: %s", exc)
        return MetricResult("llm_judge_score", 0.0, {"error": str(exc)})

    parsed = result.parsed or {}
    scores = [
        parsed.get("correctness", 0),
        parsed.get("idiomatic", 0),
        parsed.get("safety", 0),
        parsed.get("performance", 0),
    ]
    if not all(isinstance(s, int) for s in scores):
        return MetricResult("llm_judge_score", 0.0, {"error": "scores não-inteiros", "raw": parsed})

    avg = sum(scores) / (4 * 5)  # normaliza para 0..1
    return MetricResult(
        "llm_judge_score",
        round(avg, 4),
        {
            "correctness": scores[0],
            "idiomatic": scores[1],
            "safety": scores[2],
            "performance": scores[3],
            "rationale": parsed.get("rationale"),
        },
    )
