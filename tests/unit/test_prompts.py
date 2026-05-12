"""Testes dos templates de prompt e schema de output."""

from __future__ import annotations

from modernizer.llm.prompts import (
    OUTPUT_SCHEMA,
    SYSTEM_PROMPT,
    build_user_prompt,
)


def test_system_prompt_mentions_required_rules() -> None:
    assert "Decimal" in SYSTEM_PROMPT
    assert "ast.parse" in SYSTEM_PROMPT
    assert "SQLAlchemy" in SYSTEM_PROMPT


def test_output_schema_is_json_schema_object() -> None:
    assert OUTPUT_SCHEMA["type"] == "object"
    for prop in ("generated_code", "imports", "decisions", "caveats"):
        assert prop in OUTPUT_SCHEMA["properties"]
    assert OUTPUT_SCHEMA["additionalProperties"] is False


def test_build_user_prompt_includes_context_sections() -> None:
    prompt = build_user_prompt(
        source_code="CREATE FUNCTION foo() RETURNS INT AS $$ BEGIN RETURN 1; END; $$ LANGUAGE plpgsql;",
        schema_context="CREATE TABLE t(id INT);",
        parsed_summary={"object_kind": "function", "object_name": "foo"},
        semantic_report={"parameters": [], "risks": []},
        previous_errors=["SyntaxError at line 1"],
    )
    assert "CREATE FUNCTION foo" in prompt
    assert "CREATE TABLE t" in prompt
    assert "foo" in prompt
    assert "SyntaxError" in prompt
