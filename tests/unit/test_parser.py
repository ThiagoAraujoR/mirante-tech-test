"""Testes do nó de parsing."""

from __future__ import annotations

from modernizer.nodes.parser import parse_node

ANNEX_B_SQL = """
CREATE OR REPLACE FUNCTION fn_saldo_cliente(p_cliente_id BIGINT)
RETURNS NUMERIC(18,2)
LANGUAGE plpgsql
AS $$
DECLARE
    v_total NUMERIC(18,2);
BEGIN
    SELECT COALESCE(SUM(saldo), 0) INTO v_total
      FROM contas
     WHERE cliente_id = p_cliente_id AND status = 'ATIVA';
    RETURN v_total;
END;
$$;
"""


ANNEX_C_SQL = """
CREATE OR REPLACE PROCEDURE sp_atualizar_status_contas_inativas(
    IN  p_dias     INT,
    OUT p_afetadas INT
)
LANGUAGE plpgsql
AS $$
BEGIN
    UPDATE contas SET status = 'INATIVA' WHERE status = 'ATIVA';
    GET DIAGNOSTICS p_afetadas = ROW_COUNT;
END;
$$;
"""


def test_parser_extracts_function_metadata() -> None:
    out = parse_node({"source_code": ANNEX_B_SQL})
    parsed = out["parsed"]
    assert parsed.object_kind == "function"
    assert parsed.object_name == "fn_saldo_cliente"
    assert len(parsed.parameters) == 1
    assert parsed.parameters[0]["name"] == "p_cliente_id"
    assert "int" in parsed.parameters[0]["type"].lower()
    assert parsed.return_type and "numeric" in parsed.return_type.lower()


def test_parser_extracts_procedure_with_out_param() -> None:
    out = parse_node({"source_code": ANNEX_C_SQL})
    parsed = out["parsed"]
    assert parsed.object_kind == "procedure"
    assert parsed.object_name == "sp_atualizar_status_contas_inativas"
    modes = [p["mode"] for p in parsed.parameters]
    assert "IN" in modes
    assert "OUT" in modes


def test_parser_handles_empty_source() -> None:
    out = parse_node({"source_code": ""})
    assert out.get("status") == "failure"
