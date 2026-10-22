"""Unit tests for discrete tools: get_events, lookup_dtc, search_logs, current_state, respond_direct."""
from __future__ import annotations

import sqlite3
from pathlib import Path
import pytest

from tools.registry import dispatch_tool

DB_PATH = Path("data/vehicle.db")


class TestDiscreteTools:
    def test_get_events_yesterday(self) -> None:
        # Reference Query Q3: ADAS disengagements yesterday (2026-10-27)
        res = dispatch_tool(
            tool_name="get_events",
            args={
                "type": "adas_disengagement",
                "start": "2026-10-27",
                "end": "2026-10-27",
            },
            db_path=DB_PATH,
        )
        assert res["tool"] == "get_events"
        assert len(res["events"]) >= 1, "Expected ADAS events on yesterday (2026-10-27)"
        assert len(res["findings"]) >= 1
        assert "adas_disengagement" in res["findings"][0]["claim"]
        assert len(res["data_gaps"]) == 0

    def test_get_events_empty_window_returns_gap(self) -> None:
        res = dispatch_tool(
            tool_name="get_events",
            args={
                "type": "battery_overtemp_warning",
                "start": "2026-10-01",
                "end": "2026-10-05",
            },
            db_path=DB_PATH,
        )
        assert len(res["data_gaps"]) == 1
        assert res["data_gaps"][0]["reason"] == "no_events_found"

    def test_lookup_dtc_known_code(self) -> None:
        res = dispatch_tool(
            tool_name="lookup_dtc",
            args={"code": "P0A7E"},
            db_path=DB_PATH,
        )
        assert res["tool"] == "lookup_dtc"
        assert len(res["findings"]) >= 1
        assert "P0A7E" in res["findings"][0]["claim"]
        assert "temperature" in res["findings"][0]["claim"].lower() or "overtemp" in res["findings"][0]["claim"].lower()

    def test_current_state_soc(self) -> None:
        res = dispatch_tool(
            tool_name="current_state",
            args={"signal": "soc"},
            db_path=DB_PATH,
        )
        assert res["tool"] == "current_state"
        assert len(res["findings"]) == 1
        assert res["findings"][0]["unit"] == "%"
        assert 0.0 <= res["findings"][0]["value"] <= 100.0

    def test_current_state_range_per_charge(self) -> None:
        res = dispatch_tool(
            tool_name="current_state",
            args={"signal": "range_per_charge"},
            db_path=DB_PATH,
        )
        assert res["tool"] == "current_state"
        assert len(res["findings"]) == 1
        assert res["findings"][0]["unit"] == "km"
        assert res["findings"][0]["value"] > 100.0

    def test_respond_direct_control_request(self) -> None:
        res = dispatch_tool(
            tool_name="respond_direct",
            args={"kind": "control_request"},
            db_path=DB_PATH,
        )
        assert res["tool"] == "respond_direct"
        assert len(res["findings"]) == 1
        assert "cannot execute vehicle control" in res["findings"][0]["claim"]

    def test_search_logs_query(self, tmp_path: Path) -> None:
        # Create a small temp DB with logs table populated to verify search_logs
        db_file = tmp_path / "test_logs.db"
        from store.db import init_db
        conn = init_db(db_file, Path("docs/schema.sql"))
        conn.execute("INSERT INTO logs (id, ts, source, level, message) VALUES (1, 1790793000000, 'qnx', 'WARN', 'Coolant pump flow low')")
        conn.commit()
        conn.close()

        res = dispatch_tool(
            tool_name="search_logs",
            args={
                "query": "Coolant",
                "start": "2026-10-01",
                "end": "2026-10-05",
            },
            db_path=db_file,
        )
        assert res["tool"] == "search_logs"
        assert len(res["findings"]) == 1
        assert "Coolant pump flow low" in res["findings"][0]["claim"]
