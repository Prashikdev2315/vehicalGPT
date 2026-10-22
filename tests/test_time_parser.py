"""Unit tests for tools/time_parser.py."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
import pytest

from tools.time_parser import (
    DEFAULT_REF_NOW,
    DEFAULT_TIMEZONE,
    _get_tz,
    parse_iso_interval,
    parse_iso_to_epoch_ms,
    resolve_relative_time,
)


class TestTimeParser:
    def test_yesterday_resolution(self) -> None:
        # Default ref_now is 2026-10-28 23:59:59 Asia/Kolkata
        start, end = resolve_relative_time("yesterday")
        assert start == "2026-10-27"
        assert end == "2026-10-27"

    def test_today_resolution(self) -> None:
        start, end = resolve_relative_time("today")
        assert start == "2026-10-28"
        assert end == "2026-10-28"

    def test_last_2_weeks_resolution(self) -> None:
        start, end = resolve_relative_time("last 2 weeks")
        assert start == "2026-10-14"
        assert end == "2026-10-28"

    def test_last_n_days_resolution(self) -> None:
        start, end = resolve_relative_time("last 7 days")
        assert start == "2026-10-21"
        assert end == "2026-10-28"

    def test_iso_interval_passthrough(self) -> None:
        start, end = resolve_relative_time("2026-10-01/2026-10-07")
        assert start == "2026-10-01"
        assert end == "2026-10-07"

    def test_single_iso_date_passthrough(self) -> None:
        start, end = resolve_relative_time("2026-10-15")
        assert start == "2026-10-15"
        assert end == "2026-10-15"

    def test_since_day_of_week(self) -> None:
        # 2026-10-28 is a Wednesday
        start, end = resolve_relative_time("since tuesday")
        assert start == "2026-10-27"
        assert end == "2026-10-28"

    def test_invalid_expression_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="Unrecognized relative time"):
            resolve_relative_time("sometime next year")

    def test_parse_iso_date_to_epoch_ms(self) -> None:
        tz = _get_tz("Asia/Kolkata")
        # 2026-10-01 00:00:00 Asia/Kolkata (+05:30) = 2026-09-30 18:30:00 UTC
        ms_start = parse_iso_to_epoch_ms("2026-10-01", end_of_day=False)
        expected_dt = datetime(2026, 10, 1, 0, 0, 0, tzinfo=tz)
        assert ms_start == int(expected_dt.timestamp() * 1000)

        ms_end = parse_iso_to_epoch_ms("2026-10-01", end_of_day=True)
        assert ms_end > ms_start
        assert ms_end - ms_start == 86399999

    def test_parse_iso_interval_to_epoch_ms(self) -> None:
        start_ms, end_ms = parse_iso_interval("2026-10-01/2026-10-07")
        assert end_ms > start_ms
        assert (end_ms - start_ms) == (7 * 86400 * 1000 - 1)
