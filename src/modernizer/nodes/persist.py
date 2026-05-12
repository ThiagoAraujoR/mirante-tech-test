"""Nó de persistência — grava em modernization_history e em disco (results/)."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from modernizer.config import get_settings
from modernizer.db.repository import ModernizationRepository
from modernizer.state import ModernizerState, ParsedSQL, SemanticReport, ValidationReport

logger = logging.getLogger(__name__)

_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9_-]+")


def _safe_slug(value: str | None, fallback: str = "unknown") -> str:
    if not value:
        return fallback
    cleaned = _SAFE_NAME_RE.sub("_", value).strip("_")
    return cleaned or fallback


def _write_results_to_disk(
    state: ModernizerState,
    report: dict[str, Any],
    status: str,
    run_id: Any,
) -> str | None:
    """Materializa generated.py, report.json e decisions.md em <results_dir>/<slug>/."""
    settings = get_settings()
    if not settings.write_results_to_disk:
        return None

    parsed: ParsedSQL | None = state.get("parsed")
    object_name = _safe_slug(parsed.object_name if parsed else None)
    run_suffix = str(run_id).split("-")[0] if run_id else "norun"
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    out_dir = Path(settings.results_dir) / f"{timestamp}_{object_name}_{run_suffix}"

    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.warning("results: falha ao criar diretório %s: %s", out_dir, exc)
        return None

    generated = state.get("generated_code") or "# (vazio — falha de geração)\n"
    payload = {
        "run_id": str(run_id) if run_id else None,
        "status": status,
        "generated_code": state.get("generated_code"),
        "report": report,
        "error_message": state.get("error_message"),
    }
    generation = report.get("generation") or {}
    decisions = generation.get("decisions") or []
    caveats = generation.get("caveats") or []

    md_lines = [
        f"# Decisões — {object_name}",
        "",
        "## Status",
        f"- {status}",
        "",
        "## Decisões",
    ]
    for d in decisions:
        md_lines.append(
            f"- **{d.get('about')}**: {d.get('choice')} — {d.get('reason')}"
        )
    md_lines.append("")
    md_lines.append("## Caveats")
    for c in caveats:
        md_lines.append(f"- {c}")

    try:
        (out_dir / "generated.py").write_text(generated, encoding="utf-8")
        (out_dir / "report.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        (out_dir / "decisions.md").write_text("\n".join(md_lines), encoding="utf-8")
    except OSError as exc:
        logger.warning("results: falha ao escrever em %s: %s", out_dir, exc)
        return None

    logger.info("results: materializado em %s", out_dir)
    return str(out_dir)


def _build_report(state: ModernizerState) -> dict[str, Any]:
    parsed: ParsedSQL | None = state.get("parsed")
    semantic: SemanticReport | None = state.get("semantic")
    validation: ValidationReport | None = state.get("validation")
    meta = state.get("generation_meta") or {}

    return {
        "parser": {
            "object_kind": parsed.object_kind if parsed else None,
            "object_name": parsed.object_name if parsed else None,
            "parameters": parsed.parameters if parsed else [],
            "return_type": parsed.return_type if parsed else None,
            "parser_used": parsed.parser_used if parsed else None,
            "degraded": parsed.degraded if parsed else None,
            "parse_error": parsed.parse_error if parsed else None,
        }
        if parsed
        else {},
        "semantic": asdict(semantic) if semantic else {},
        "generation": {
            "provider": meta.get("provider"),
            "model": meta.get("model"),
            "input_tokens": meta.get("input_tokens"),
            "output_tokens": meta.get("output_tokens"),
            "cost_usd": meta.get("cost_usd"),
            "latency_ms": meta.get("latency_ms"),
            "decisions": meta.get("decisions"),
            "caveats": meta.get("caveats"),
            "imports": meta.get("imports"),
            "attempts": state.get("attempts", 0),
        },
        "validation": asdict(validation) if validation else {},
        "previous_errors": state.get("previous_errors", []),
    }


def _resolve_status(state: ModernizerState) -> str:
    if state.get("status") in {"failure", "partial", "success"}:
        return state["status"]
    validation: ValidationReport | None = state.get("validation")
    if validation is None:
        return "failure"
    if not validation.static_ok:
        return "failure"
    if validation.dynamic_ok is False:
        return "partial"
    if validation.dynamic_ok is None and validation.dynamic_error:
        return "partial"
    return "success"


async def persist_node(state: ModernizerState) -> dict[str, Any]:
    status = _resolve_status(state)
    report = _build_report(state)
    meta = state.get("generation_meta") or {}

    repo = ModernizationRepository()
    cost = meta.get("cost_usd")
    run_id = await repo.save_run(
        source_code=state.get("source_code", ""),
        generated_code=state.get("generated_code"),
        report=report,
        status=status,
        llm_provider=meta.get("provider"),
        llm_model=meta.get("model"),
        latency_ms=meta.get("latency_ms"),
        cost_usd=Decimal(str(cost)) if cost is not None else None,
        error_message=state.get("error_message"),
    )

    results_path = _write_results_to_disk(state, report, status, run_id)
    if results_path:
        report.setdefault("artifacts", {})["results_dir"] = results_path

    logger.info("persist: status=%s run_id=%s results_dir=%s", status, run_id, results_path)
    return {
        "status": status,
        "report": report,
        "run_id": str(run_id) if run_id else None,
    }
