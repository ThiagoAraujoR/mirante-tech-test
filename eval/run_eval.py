"""Roda a avaliação automática nos Anexos B–F e registra scores."""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from pathlib import Path
from typing import Any

import httpx

from eval.metrics import (
    ast_parse_metric,
    exec_equivalence_from_report,
    llm_judge_metric,
    structural_similarity_metric,
)
from modernizer.db.repository import ModernizationRepository

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "examples"
RESULTS = ROOT / "results"

API_URL = os.environ.get("MODERNIZER_API", "http://localhost:2024")

ANNEXES = [
    ("annex_b", "annex_b_fn_saldo_cliente.sql"),
    ("annex_c", "annex_c_sp_atualizar_status.sql"),
    ("annex_d", "annex_d_sp_transferir.sql"),
    ("annex_e", "annex_e_sp_processar_lote_taxas.sql"),
    ("annex_f", "annex_f_sp_relatorio_mensal.sql"),
]


async def _modernize(client: httpx.AsyncClient, source: str, schema: str) -> dict[str, Any]:
    response = await client.post(
        f"{API_URL}/modernize",
        json={"source_code": source, "schema": schema},
        timeout=300,
    )
    response.raise_for_status()
    return response.json()


async def evaluate_annex(
    client: httpx.AsyncClient,
    repo: ModernizationRepository,
    annex_name: str,
    filename: str,
    schema_sql: str,
) -> dict[str, Any]:
    sql_path = EXAMPLES / filename
    source_sql = sql_path.read_text(encoding="utf-8")
    print(f"[{annex_name}] modernizando ...")
    response = await _modernize(client, source_sql, schema_sql)
    generated = response.get("generated_code") or ""
    report = response.get("report") or {}
    run_id_str = response.get("run_id")
    run_id = uuid.UUID(run_id_str) if run_id_str else None

    sql_kinds = []
    body = report.get("parser", {})
    for stmt in (body or {}).get("body_statement_kinds", []) or []:
        if isinstance(stmt, dict) and stmt.get("kind"):
            sql_kinds.append(stmt["kind"])

    metrics = [
        ast_parse_metric(generated),
        structural_similarity_metric(sql_kinds, generated),
        exec_equivalence_from_report(report),
    ]

    # llm_judge é custoso; controlado por env
    if os.environ.get("EVAL_LLM_JUDGE", "true").lower() == "true":
        metrics.append(await llm_judge_metric(source_sql, generated))

    for m in metrics:
        await repo.save_evaluation(
            run_id=run_id,
            annex=annex_name,
            metric_name=m.name,
            metric_value=m.value,
            details=m.details,
        )
        print(f"  {m.name} = {m.value:.4f}")

    return {
        "annex": annex_name,
        "status": response.get("status"),
        "metrics": {m.name: m.value for m in metrics},
        "details": {m.name: m.details for m in metrics},
    }


async def main() -> None:
    schema_sql = (ROOT / "sql" / "legacy_schema.sql").read_text(encoding="utf-8")
    repo = ModernizationRepository()
    results: list[dict[str, Any]] = []
    async with httpx.AsyncClient() as client:
        for annex, filename in ANNEXES:
            try:
                results.append(await evaluate_annex(client, repo, annex, filename, schema_sql))
            except Exception as exc:  # noqa: BLE001
                print(f"[{annex}] erro: {exc}")
                results.append({"annex": annex, "error": str(exc)})

    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / "eval_report.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nRelatório completo em {out}")


if __name__ == "__main__":
    asyncio.run(main())
