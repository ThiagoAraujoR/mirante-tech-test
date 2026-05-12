"""Testes do nó de análise semântica."""

from __future__ import annotations

from modernizer.nodes.analyzer import analyze_node
from modernizer.nodes.parser import parse_node

ANNEX_E_SQL = """
CREATE OR REPLACE PROCEDURE sp_processar_lote_taxas(IN p_data DATE)
LANGUAGE plpgsql AS $$
DECLARE
    cur_t CURSOR FOR SELECT id FROM transacoes;
    v_id BIGINT;
BEGIN
    OPEN cur_t;
    LOOP
        FETCH cur_t INTO v_id;
        EXIT WHEN NOT FOUND;
    END LOOP;
    CLOSE cur_t;
END;
$$;
"""


ANNEX_D_SQL = """
CREATE OR REPLACE PROCEDURE sp_x(IN p_a BIGINT)
LANGUAGE plpgsql AS $$
BEGIN
    SELECT 1 FOR UPDATE;
    RAISE EXCEPTION 'erro';
EXCEPTION WHEN OTHERS THEN
    RAISE;
END;
$$;
"""


def test_analyzer_detects_cursor() -> None:
    parsed = parse_node({"source_code": ANNEX_E_SQL})["parsed"]
    semantic = analyze_node({"parsed": parsed})["semantic"]
    tags = {r["tag"] for r in semantic.risks}
    assert "explicit_cursor" in tags
    assert semantic.strategy_hints.get("cursor")


def test_analyzer_detects_lock_and_exception() -> None:
    parsed = parse_node({"source_code": ANNEX_D_SQL})["parsed"]
    semantic = analyze_node({"parsed": parsed})["semantic"]
    tags = {r["tag"] for r in semantic.risks}
    assert "row_lock" in tags
    assert "raise_stmt" in tags
    assert "exception_block" in tags
