#!/usr/bin/env python3
"""Roda o pipeline em cada anexo e persiste o resultado em results/."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "examples"
RESULTS = ROOT / "results"
SCHEMA_PATH = ROOT / "sql" / "legacy_schema.sql"

API_URL = os.environ.get("MODERNIZER_API", "http://localhost:2024")


ANNEXES = [
    ("annex_b", "annex_b_fn_saldo_cliente.sql"),
    ("annex_c", "annex_c_sp_atualizar_status.sql"),
    ("annex_d", "annex_d_sp_transferir.sql"),
    ("annex_e", "annex_e_sp_processar_lote_taxas.sql"),
    ("annex_f", "annex_f_sp_relatorio_mensal.sql"),
]


async def run_one(client: httpx.AsyncClient, name: str, sql_path: Path, schema: str) -> dict:
    source = sql_path.read_text(encoding="utf-8")
    payload = {"source_code": source, "schema": schema}
    print(f"[{name}] enviando para {API_URL}/modernize ...")
    response = await client.post(f"{API_URL}/modernize", json=payload, timeout=300)
    response.raise_for_status()
    return response.json()


def materialize(name: str, response: dict) -> None:
    out_dir = RESULTS / name
    out_dir.mkdir(parents=True, exist_ok=True)
    generated = response.get("generated_code") or "# (vazio — falha de geração)\n"
    (out_dir / "generated.py").write_text(generated, encoding="utf-8")
    (out_dir / "report.json").write_text(
        json.dumps(response, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    decisions = (response.get("report", {}).get("generation") or {}).get("decisions") or []
    caveats = (response.get("report", {}).get("generation") or {}).get("caveats") or []
    md_lines = [f"# Decisões — {name}", "", "## Status", f"- {response.get('status')}", "", "## Decisões"]
    for d in decisions:
        md_lines.append(f"- **{d.get('about')}**: {d.get('choice')} — {d.get('reason')}")
    md_lines.append("\n## Caveats")
    for c in caveats:
        md_lines.append(f"- {c}")
    (out_dir / "decisions.md").write_text("\n".join(md_lines), encoding="utf-8")
    print(f"[{name}] materializado em {out_dir}")


async def main() -> None:
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    async with httpx.AsyncClient() as client:
        for name, filename in ANNEXES:
            sql_path = EXAMPLES / filename
            try:
                resp = await run_one(client, name, sql_path, schema)
                materialize(name, resp)
            except httpx.HTTPError as exc:
                print(f"[{name}] erro HTTP: {exc}")
            except Exception as exc:  # noqa: BLE001
                print(f"[{name}] erro: {exc}")


if __name__ == "__main__":
    asyncio.run(main())
