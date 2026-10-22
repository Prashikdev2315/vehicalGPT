"""Tests for GBNF grammar compilation and deterministic time pre-pass."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo
import pytest

from slm.grammar import ENFORCED_SCHEMA_KEYWORDS, get_tools_gbnf
from slm.time_prepass import (
    extract_time_expression,
    format_time_hint,
    resolve_time_prepass,
    validate_tool_args_against_hints,
)

KOLKATA_TZ = ZoneInfo("Asia/Kolkata")
REF_NOW = datetime(2026, 10, 28, 9, 0, 0, tzinfo=KOLKATA_TZ)


def test_gbnf_grammar_compilation() -> None:
    """Verify that tools.schema.json compiles to valid non-empty GBNF grammar."""
    gbnf = get_tools_gbnf()
    assert isinstance(gbnf, str)
    assert len(gbnf) > 1000
    assert "root ::=" in gbnf
    assert "explain-change" in gbnf or "explain_change" in gbnf or "timeline-before" in gbnf or "timeline_before" in gbnf

    # Check that documented keywords are tracked
    assert "type" in ENFORCED_SCHEMA_KEYWORDS
    assert "oneOf" in ENFORCED_SCHEMA_KEYWORDS
    assert "required" in ENFORCED_SCHEMA_KEYWORDS


def test_time_prepass_yesterday() -> None:
    """Verify relative 'yesterday' resolves correctly and formats prompt hint."""
    query = "Why did ADAS disengage yesterday?"
    expr = extract_time_expression(query)
    assert expr == "yesterday"

    resolved = resolve_time_prepass(query, ref_now=REF_NOW)
    assert resolved == ("2026-10-27", "2026-10-27")

    hint = format_time_hint(query, ref_now=REF_NOW)
    assert "resolved_start='2026-10-27'" in hint
    assert "resolved_end='2026-10-27'" in hint


def test_time_prepass_last_2_weeks() -> None:
    """Verify 'last 2 weeks' resolves correctly."""
    query = "What is the trend of range per charge over the last 2 weeks?"
    resolved = resolve_time_prepass(query, ref_now=REF_NOW)
    assert resolved == ("2026-10-14", "2026-10-28")


def test_validate_tool_args_against_hints() -> None:
    """Verify parameter validation catches mismatches against pre-pass time hints."""
    resolved = ("2026-10-27", "2026-10-27")

    # Valid args matching hint
    valid_args = {"type": "adas_disengagement", "start": "2026-10-27", "end": "2026-10-27"}
    ok, err = validate_tool_args_against_hints("get_events", valid_args, resolved)
    assert ok is True
    assert err is None

    # Invalid args deviating from hint
    bad_args = {"type": "adas_disengagement", "start": "2026-10-28", "end": "2026-10-28"}
    ok, err = validate_tool_args_against_hints("get_events", bad_args, resolved)
    assert ok is False
    assert "do not match injected time hint" in err
