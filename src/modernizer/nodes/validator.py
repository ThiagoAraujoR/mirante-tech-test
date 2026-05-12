"""Nó de validação — estática (ast.parse + ruff) e dinâmica (sandbox)."""

from __future__ import annotations

import ast
import asyncio
import logging
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from modernizer.config import get_settings
from modernizer.sandbox.runner import run_dynamic_check
from modernizer.state import ModernizerState, ParsedSQL, ValidationReport

logger = logging.getLogger(__name__)


def _static_parse(code: str) -> tuple[bool, list[str]]:
    try:
        ast.parse(code)
        return True, []
    except SyntaxError as exc:
        return False, [f"SyntaxError at line {exc.lineno}: {exc.msg}"]


def _ruff_check(code: str) -> list[str]:
    """Roda ruff sobre um arquivo temporário; warnings retornados como strings."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", delete=False, encoding="utf-8"
    ) as tmp:
        tmp.write(code)
        tmp_path = Path(tmp.name)
    try:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "ruff",
                "check",
                "--select=E,F,W,B",
                "--output-format=concise",
                str(tmp_path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        lines = [
            ln.replace(str(tmp_path), "<generated>").strip()
            for ln in result.stdout.splitlines()
            if ln.strip()
        ]
        return lines
    except subprocess.TimeoutExpired:
        return ["ruff: timeout"]
    except FileNotFoundError:
        return ["ruff: binário não encontrado (instale com pip install ruff)"]
    finally:
        tmp_path.unlink(missing_ok=True)


async def validate_node(state: ModernizerState) -> dict[str, Any]:
    settings = get_settings()
    code = state.get("generated_code", "")
    parsed: ParsedSQL | None = state.get("parsed")
    report = ValidationReport()

    if not code.strip():
        report.syntax_errors = ["código gerado vazio"]
        return {"validation": report}

    static_ok, syntax_errors = _static_parse(code)
    report.static_ok = static_ok
    report.syntax_errors = syntax_errors

    if not static_ok:
        logger.warning("validate: ast.parse falhou — %s", syntax_errors)
        return {"validation": report}

    # Linting é informativo, não bloqueia
    report.lint_warnings = await asyncio.to_thread(_ruff_check, code)

    if settings.enable_dynamic_validation and parsed and parsed.object_name:
        try:
            ok, mismatches, dyn_error = await asyncio.to_thread(
                run_dynamic_check,
                sandbox_url=settings.sandbox_database_url.replace(
                    "+asyncpg", "+psycopg"
                ),
                generated_code=code,
                object_name=parsed.object_name,
                object_kind=parsed.object_kind,
                parameters=parsed.parameters,
                source_sql=parsed.raw_source,
            )
            report.dynamic_ok = ok
            report.dynamic_mismatches = mismatches
            report.dynamic_error = dyn_error
        except Exception as exc:
            logger.exception("validação dinâmica falhou")
            report.dynamic_ok = None
            report.dynamic_error = f"unhandled: {exc}"

    logger.info(
        "validate: static_ok=%s dynamic_ok=%s lint_warnings=%d",
        report.static_ok,
        report.dynamic_ok,
        len(report.lint_warnings),
    )
    return {"validation": report}
