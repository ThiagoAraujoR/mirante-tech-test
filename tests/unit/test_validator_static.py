"""Testes da validação estática do código gerado."""

from __future__ import annotations

import pytest

from modernizer.nodes.validator import _static_parse


def test_static_parse_accepts_valid_code() -> None:
    code = "def foo() -> int:\n    return 1\n"
    ok, errors = _static_parse(code)
    assert ok is True
    assert errors == []


def test_static_parse_rejects_invalid_code() -> None:
    code = "def foo(:\n    return\n"
    ok, errors = _static_parse(code)
    assert ok is False
    assert errors


@pytest.mark.asyncio
async def test_validate_node_returns_report() -> None:
    from modernizer.nodes.validator import validate_node

    state = {"generated_code": "x = 1\n"}
    result = await validate_node(state)
    assert "validation" in result
    assert result["validation"].static_ok is True
