"""Deterministic time and relative date parser for VehicleGPT.

Resolves natural-language relative expressions (e.g. 'yesterday', 'last 2 weeks',
'since Tuesday') into schema-compliant ISO 8601 strings in the vehicle timezone,
and parses ISO strings/intervals to epoch milliseconds for tool database queries.

Rules:
- Evaluates against vehicle clock and timezone (default Asia/Kolkata).
- No model guessing; purely deterministic date arithmetic.
"""
from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo


def _get_tz(tz_name: str) -> Any:
    """Return timezone object with graceful fallback if system tz database is missing."""
    try:
        return ZoneInfo(tz_name)
    except Exception:
        if tz_name == "Asia/Kolkata":
            return timezone(timedelta(hours=5, minutes=30), name="Asia/Kolkata")
        return timezone.utc


DEFAULT_TIMEZONE = "Asia/Kolkata"
DEFAULT_REF_NOW = datetime(2026, 10, 28, 23, 59, 59, tzinfo=_get_tz(DEFAULT_TIMEZONE))

DAY_NAMES = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def resolve_relative_time(
    expr: str,
    ref_now: datetime | None = None,
    tz_name: str = DEFAULT_TIMEZONE,
) -> tuple[str, str]:
    """Resolve a relative time expression into (start_iso, end_iso) date strings.

    Args:
        expr: Expression such as 'yesterday', 'today', 'last 2 weeks', 'last 7 days',
              'this week', 'last week', 'since tuesday', or an ISO interval 'YYYY-MM-DD/YYYY-MM-DD'.
        ref_now: Reference 'now' datetime (defaults to 2026-10-28 23:59:59 Asia/Kolkata).
        tz_name: Vehicle timezone name.

    Returns:
        tuple of (start_iso, end_iso) formatted as 'YYYY-MM-DD' or 'YYYY-MM-DDTHH:MM:SS'.
    """
    tz = _get_tz(tz_name)
    if ref_now is None:
        ref_now = DEFAULT_REF_NOW
    elif ref_now.tzinfo is None:
        ref_now = ref_now.replace(tzinfo=tz)
    else:
        ref_now = ref_now.astimezone(tz)

    ref_date = ref_now.date()
    normalized = expr.strip().lower()

    # ISO Interval: "YYYY-MM-DD/YYYY-MM-DD"
    if "/" in normalized:
        parts = normalized.split("/", 1)
        return parts[0].strip(), parts[1].strip()

    # Date range: "YYYY-MM-DD to YYYY-MM-DD", "between YYYY-MM-DD and YYYY-MM-DD"
    m_range = re.match(r"^(?:between\s+)?(\d{4}-\d{2}-\d{2})\s+(?:to|and|-)\s+(\d{4}-\d{2}-\d{2})$", normalized)
    if m_range:
        return m_range.group(1), m_range.group(2)

    # Yesterday
    if normalized == "yesterday":
        y_date = ref_date - timedelta(days=1)
        y_str = y_date.strftime("%Y-%m-%d")
        return y_str, y_str

    # Today
    if normalized == "today":
        t_str = ref_date.strftime("%Y-%m-%d")
        return t_str, t_str

    # This week (Monday of current week to today)
    if normalized in ("this week", "current week"):
        start_date = ref_date - timedelta(days=ref_date.weekday())
        return start_date.strftime("%Y-%m-%d"), ref_date.strftime("%Y-%m-%d")

    # Last week (Monday to Sunday of previous week)
    if normalized in ("last week", "past week"):
        current_monday = ref_date - timedelta(days=ref_date.weekday())
        last_monday = current_monday - timedelta(days=7)
        last_sunday = last_monday + timedelta(days=6)
        return last_monday.strftime("%Y-%m-%d"), last_sunday.strftime("%Y-%m-%d")

    # Last N days / past N days
    m_days = re.match(r"^(?:last|past)\s+(\d+)\s+days?$", normalized)
    if m_days:
        n_days = int(m_days.group(1))
        start_date = ref_date - timedelta(days=n_days)
        return start_date.strftime("%Y-%m-%d"), ref_date.strftime("%Y-%m-%d")

    # Last N weeks / past N weeks
    m_weeks = re.match(r"^(?:last|past)\s+(\d+)\s+weeks?$", normalized)
    if m_weeks:
        n_weeks = int(m_weeks.group(1))
        start_date = ref_date - timedelta(days=n_weeks * 7)
        return start_date.strftime("%Y-%m-%d"), ref_date.strftime("%Y-%m-%d")

    # Since <DayOfWeek> (e.g. "since tuesday")
    m_since = re.match(r"^since\s+([a-z]+)$", normalized)
    if m_since:
        day_str = m_since.group(1)
        if day_str in DAY_NAMES:
            target_weekday = DAY_NAMES.index(day_str)
            days_ago = (ref_date.weekday() - target_weekday) % 7
            if days_ago == 0:
                days_ago = 7  # prior week's day if today is that day
            start_date = ref_date - timedelta(days=days_ago)
            return start_date.strftime("%Y-%m-%d"), ref_date.strftime("%Y-%m-%d")

    # If it's already a single ISO date: "2026-10-15"
    if re.match(r"^\d{4}-\d{2}-\d{2}$", normalized):
        return normalized, normalized

    raise ValueError(f"Unrecognized relative time expression: '{expr}'")


def parse_iso_to_epoch_ms(
    iso_str: str,
    tz_name: str = DEFAULT_TIMEZONE,
    end_of_day: bool = False,
) -> int:
    """Parse an ISO 8601 string to epoch milliseconds in the vehicle timezone.

    If iso_str is a date 'YYYY-MM-DD':
        - end_of_day=False -> midnight 00:00:00.000
        - end_of_day=True  -> end of day 23:59:59.999
    """
    tz = _get_tz(tz_name)
    s = iso_str.strip()

    # Date only: YYYY-MM-DD
    if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
        d = date.fromisoformat(s)
        t = time(23, 59, 59, 999000) if end_of_day else time(0, 0, 0)
        dt = datetime.combine(d, t, tzinfo=tz)
        return int(dt.timestamp() * 1000)

    # Full datetime with Z or offset or naive
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    return int(dt.timestamp() * 1000)


def parse_iso_interval(
    interval_str: str,
    tz_name: str = DEFAULT_TIMEZONE,
) -> tuple[int, int]:
    """Parse an ISO interval 'start/end' into (start_ms, end_ms).

    Dates without time start at 00:00:00 and end at 23:59:59.999.
    """
    if "/" not in interval_str:
        raise ValueError(f"Invalid ISO interval format (missing '/'): '{interval_str}'")
    start_str, end_str = interval_str.split("/", 1)
    start_ms = parse_iso_to_epoch_ms(start_str, tz_name=tz_name, end_of_day=False)
    end_ms = parse_iso_to_epoch_ms(end_str, tz_name=tz_name, end_of_day=True)
    return start_ms, end_ms
