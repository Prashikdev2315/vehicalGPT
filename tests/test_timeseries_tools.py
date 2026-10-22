"""Unit tests for time-series and comparison tools: trend, compare, largest_change."""
from __future__ import annotations

from pathlib import Path
import pytest

from tools.registry import dispatch_tool

DB_PATH = Path("data/vehicle.db")


class TestTimeSeriesTools:
    def test_trend_range_per_charge(self) -> None:
        res = dispatch_tool(
            tool_name="trend",
            args={
                "metric": "range_per_charge",
                "start": "2026-10-01",
                "end": "2026-10-28",
                "granularity": "day",
            },
            db_path=DB_PATH,
        )
        assert res["tool"] == "trend"
        assert len(res["findings"]) >= 1
        claim = res["findings"][0]["claim"]
        assert "range_per_charge" in claim
        assert "declined" in claim.lower() or "dropped" in claim.lower()
        assert res["findings"][0]["unit"] == "%"
        assert res["findings"][0]["value"] < 0  # negative change

    def test_compare_city_vs_highway(self) -> None:
        # Reference Query Q5: city vs highway energy comparison
        res = dispatch_tool(
            tool_name="compare",
            args={
                "metric": "energy_per_km",
                "segment_a": "city",
                "segment_b": "highway",
                "start": "2026-10-01",
                "end": "2026-10-28",
            },
            db_path=DB_PATH,
        )
        assert res["tool"] == "compare"
        assert len(res["findings"]) >= 1
        f1 = res["findings"][0]
        # City EPK vs Highway EPK computed gap
        assert f1["value"] is not None
        assert f1["unit"] == "%"
        assert abs(f1["value"]) > 0.0
        assert "energy_per_km" in f1["claim"]
        assert len(res["data_gaps"]) == 0

    def test_largest_change_range_drop(self) -> None:
        # Reference Query Q2 / Change point detection
        res = dispatch_tool(
            tool_name="largest_change",
            args={
                "metric": "range_per_charge",
                "start": "2026-10-01",
                "end": "2026-10-28",
                "direction": "drop",
            },
            db_path=DB_PATH,
        )
        assert res["tool"] == "largest_change"
        assert len(res["findings"]) >= 1
        f1 = res["findings"][0]
        assert "drop" in f1["claim"].lower() or "dropped" in f1["claim"].lower()
        # Ensure change-point date is reported
        assert "2026-10-" in f1["claim"]
        assert f1["confidence"] >= 0.70
