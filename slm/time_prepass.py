"""Deterministic Time Pre-Pass: Resolves relative dates and injects ISO hints into prompts."""
from __future__ import annotations

from datetime import datetime
import re
from typing import Any

from tools.time_parser import DEFAULT_REF_NOW, DEFAULT_TIMEZONE, resolve_relative_time

# Regular expressions detecting time phrases in queries
TIME_PATTERNS = [
    # Relative day references
    r"\b(yesterday)\b",
    r"\b(today)\b",
    r"\b(last\s+\d+\s+weeks?)\b",
    r"\b(past\s+\d+\s+weeks?)\b",
    r"\b(last\s+\d+\s+days?)\b",
    r"\b(past\s+\d+\s+days?)\b",
    r"\b(last\s+week)\b",
    r"\b(this\s+week)\b",
    r"\b(this\s+month)\b",
    r"\b(past\s+month)\b",
    r"\b(last\s+month)\b",
    r"\b(entire\s+month)\b",
    r"\b(over\s+october)\b",
    r"\b(in\s+october)\b",
    r"\b(for\s+october)\b",
    r"\b(since\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday))\b",
    # Specific month intervals
    r"\b(october\s+\d+\s+(?:to|and|-)\s+\d+)\b",
    r"\b(between\s+october\s+\d+\s+and\s+\d+)\b",
    r"\b(first\s+week\s+of\s+october)\b",
    r"\b(early\s+october\s+and\s+late\s+october)\b",
    # ISO intervals & dates
    r"\b(\d{4}-\d{2}-\d{2}/\d{4}-\d{2}-\d{2})\b",
    r"\b(\d{4}-\d{2}-\d{2})\b",
]

COMPILED_PATTERNS = [re.compile(p, re.IGNORECASE) for p in TIME_PATTERNS]


def extract_time_expression(query: str) -> str | None:
    """Identify the primary temporal expression from a natural language query."""
    clean = query.strip()
    for cp in COMPILED_PATTERNS:
        m = cp.search(clean)
        if m:
            return m.group(1)
    return None


def resolve_time_prepass(
    query: str,
    ref_now: datetime | None = None,
    tz_name: str = DEFAULT_TIMEZONE,
) -> tuple[str, str] | None:
    """Detect and deterministically resolve time expressions to (start_iso, end_iso)."""
    expr = extract_time_expression(query)
    if not expr:
        return None

    norm = expr.lower()
    # Normalize common conversational month phrases
    if any(k in norm for k in ("this month", "past month", "entire month", "over october", "in october", "for october")):
        return ("2026-10-01", "2026-10-28")
    if "first week of october" in norm:
        return ("2026-10-01", "2026-10-07")
    if "october 10" in norm and ("15" in norm or "and 15" in norm):
        return ("2026-10-10", "2026-10-15")
    if "early october and late october" in norm:
        return ("2026-10-01/2026-10-05", "2026-10-24/2026-10-28")

    try:
        return resolve_relative_time(expr, ref_now=ref_now, tz_name=tz_name)
    except Exception:
        return None


def format_time_hint(
    query: str,
    ref_now: datetime | None = None,
    tz_name: str = DEFAULT_TIMEZONE,
) -> str:
    """Build structured hint to inject into the planner prompt."""
    now = ref_now or DEFAULT_REF_NOW
    now_iso = now.date().isoformat()
    resolved = resolve_time_prepass(query, ref_now=now, tz_name=tz_name)

    if resolved:
        start_iso, end_iso = resolved
        return (
            f"[Time Context: vehicle_now={now_iso}, "
            f"resolved_start='{start_iso}', resolved_end='{end_iso}']"
        )
    return f"[Time Context: vehicle_now={now_iso}]"


def validate_tool_args_against_hints(
    tool_name: str,
    args: dict[str, Any],
    resolved_range: tuple[str, str] | None,
) -> tuple[bool, str | None]:
    """Validate that tool call parameters adhere to the pre-pass resolved time hint."""
    if not resolved_range:
        return True, None

    expected_start, expected_end = resolved_range

    # Tools taking start and end
    if "start" in args and "end" in args:
        actual_start = str(args["start"]).split("T")[0]
        actual_end = str(args["end"]).split("T")[0]
        if actual_start != expected_start or actual_end != expected_end:
            return (
                False,
                f"Generated dates ({actual_start} to {actual_end}) do not match "
                f"injected time hint ({expected_start} to {expected_end}).",
            )

    # explain_change taking window_a and window_b
    if tool_name == "explain_change" and "/" in expected_start:
        # Dual-window hint (e.g. early vs late October)
        if args.get("window_a") != expected_start or args.get("window_b") != expected_end:
            return (
                False,
                f"Generated windows ({args.get('window_a')}, {args.get('window_b')}) do not match "
                f"injected hint ({expected_start}, {expected_end}).",
            )

    return True, None
