"""Templates de prompt da etapa de geração."""

from __future__ import annotations

import json
from typing import Any

SYSTEM_PROMPT = """Você é um engenheiro de software especialista em modernização \
de sistemas legados. Sua tarefa é traduzir stored procedures PL/pgSQL para módulos \
Python 3.14 idiomáticos, preservando a semântica de negócio.

## Regras de tradução

1. **Estratégia híbrida pragmática**: queries SELECT/UPDATE/INSERT/DELETE devem \
permanecer como SQL (via SQLAlchemy Core `text()` ou expressões Core), executadas \
contra a conexão do banco. Apenas controle de fluxo (IF, LOOP, EXCEPTION, CASE) \
é reescrito em Python.

2. **Tipos**: use `decimal.Decimal` para NUMERIC, `datetime.date`/`datetime` para \
DATE/TIMESTAMP, `int` para BIGINT, `dict[str, Any]` para JSONB. Adicione type hints \
em todas as funções.

3. **Cursors**: traduza para SQL set-based quando possível (UPDATE com subquery, \
INSERT ... SELECT). Cursor explícito em loop deve virar uma única query ou um \
fetch em lote (`.scalars().all()` ou `.mappings().all()`).

4. **FOR UPDATE**: use `SELECT ... FOR UPDATE` via `text()` ou \
`with_for_update()` no SQLAlchemy.

5. **RAISE EXCEPTION**: mapeie para uma classe customizada \
`ModernizerBusinessError(Exception)` declarada no topo do módulo.

6. **EXCEPTION WHEN OTHERS**: bloco `try/except Exception as exc:` que registra \
em log de auditoria e relança.

7. **Procedures sem retorno**: função retorna `None`.

8. **Functions com OUT params**: retorne uma dataclass ou tuple nomeada.

9. **RETURN QUERY / SETOF**: função retorna `list[dict[str, Any]]`.

10. **Transações**: o caller (geralmente um session manager) gerencia a transação. \
A função aceita uma `Connection` ou `Session` como primeiro parâmetro.

11. **Idiomático**: use snake_case, docstrings PT-BR curtas, organize imports.

12. **Não invente comportamento**: se a tradução tiver ambiguidade, registre em \
`caveats` no output estruturado.

## Critérios de aceitação automatizados

- O código DEVE passar em `ast.parse(...)` sem erros.
- Imports no topo, agrupados.
- A função principal DEVE ter o mesmo nome da procedure original.
- Nenhuma chamada a APIs externas além de SQLAlchemy/psycopg.

Você emite a resposta exclusivamente pelo tool/structured output fornecido. \
Não inclua texto fora do JSON."""


OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "generated_code": {
            "type": "string",
            "description": (
                "Módulo Python 3.14 completo, com imports, exceções customizadas "
                "(se necessário) e a função principal."
            ),
        },
        "imports": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Lista plana dos módulos importados pelo código.",
        },
        "decisions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "about": {"type": "string"},
                    "choice": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["about", "choice", "reason"],
                "additionalProperties": False,
            },
            "description": "Decisões de tradução relevantes (cursor, FOR UPDATE, CTE).",
        },
        "caveats": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Casos onde a tradução é parcial ou exige revisão humana.",
        },
    },
    "required": ["generated_code", "imports", "decisions", "caveats"],
    "additionalProperties": False,
}


def build_user_prompt(
    *,
    source_code: str,
    schema_context: str | None,
    parsed_summary: dict[str, Any],
    semantic_report: dict[str, Any],
    previous_errors: list[str] | None = None,
) -> str:
    parts: list[str] = []
    parts.append("## Stored procedure original (PL/pgSQL)\n```sql\n" + source_code + "\n```")

    if schema_context:
        parts.append("## Schema do banco legado\n```sql\n" + schema_context + "\n```")

    parts.append(
        "## Resumo da AST (parsed)\n```json\n"
        + json.dumps(parsed_summary, ensure_ascii=False, indent=2)
        + "\n```"
    )
    parts.append(
        "## Sumário semântico (params, riscos, estratégia recomendada)\n```json\n"
        + json.dumps(semantic_report, ensure_ascii=False, indent=2)
        + "\n```"
    )

    if previous_errors:
        parts.append(
            "## Erros da tentativa anterior — corrija-os nesta versão\n"
            + "\n".join(f"- {e}" for e in previous_errors)
        )

    parts.append(
        "## Tarefa\n"
        "Produza o módulo Python equivalente seguindo as regras do system prompt. "
        "Emita a resposta pelo tool/JSON schema."
    )
    return "\n\n".join(parts)


JUDGE_SYSTEM_PROMPT = """Você é um revisor sênior de migrações SQL→Python. Avalie a \
qualidade da tradução de uma stored procedure PL/pgSQL para Python, em quatro eixos:

- correctness (1-5): a lógica de negócio foi preservada?
- idiomatic (1-5): o código é idiomático em Python 3.14 / SQLAlchemy?
- safety (1-5): há tratamento adequado de erros, NULLs e transações?
- performance (1-5): a tradução evita N+1, faz uso adequado de SQL set-based?

Responda exclusivamente pelo schema JSON fornecido.
"""


JUDGE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "correctness": {"type": "integer", "minimum": 1, "maximum": 5},
        "idiomatic": {"type": "integer", "minimum": 1, "maximum": 5},
        "safety": {"type": "integer", "minimum": 1, "maximum": 5},
        "performance": {"type": "integer", "minimum": 1, "maximum": 5},
        "rationale": {"type": "string"},
    },
    "required": ["correctness", "idiomatic", "safety", "performance", "rationale"],
    "additionalProperties": False,
}


def build_judge_user_prompt(source_code: str, generated_code: str) -> str:
    return (
        "## SQL original\n```sql\n"
        + source_code
        + "\n```\n\n## Python gerado\n```python\n"
        + generated_code
        + "\n```\n\nAvalie usando o schema."
    )
