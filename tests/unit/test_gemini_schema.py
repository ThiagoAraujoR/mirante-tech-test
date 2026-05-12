"""Sanitização de schema para o Gemini."""

from __future__ import annotations

from modernizer.llm.gemini_provider import _sanitize_schema_for_gemini


def test_sanitize_removes_additional_properties() -> None:
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "x": {"type": "string", "title": "X", "default": ""},
        },
    }
    out = _sanitize_schema_for_gemini(schema)
    assert "additionalProperties" not in out
    assert "title" not in out["properties"]["x"]
    assert "default" not in out["properties"]["x"]


def test_sanitize_preserves_nested_structures() -> None:
    schema = {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {"k": {"type": "string"}},
                },
            }
        },
    }
    out = _sanitize_schema_for_gemini(schema)
    inner = out["properties"]["items"]["items"]
    assert "additionalProperties" not in inner
    assert inner["properties"]["k"]["type"] == "string"
