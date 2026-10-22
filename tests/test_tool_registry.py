"""Unit tests for tool registry, alias mapping, and schema validation."""
from __future__ import annotations

import jsonschema
import pytest

from tools.base import make_error_packet, make_evidence_packet, validate_evidence_packet
from tools.registry import normalize_signal_name, register_tool, validate_tool_call, dispatch_tool


class TestToolRegistry:
    def test_alias_normalization(self) -> None:
        assert normalize_signal_name("energy_per_km") == "energy_per_km"
        assert normalize_signal_name("fuel_efficiency") == "energy_per_km"
        assert normalize_signal_name("mileage") == "energy_per_km"
        assert normalize_signal_name("efficiency") == "energy_per_km"
        assert normalize_signal_name("range") == "range_per_charge"
        assert normalize_signal_name("battery_level") == "soc"
        assert normalize_signal_name("speed") == "vehicle_speed"
        assert normalize_signal_name("completely_unknown_signal_xyz") is None

    def test_validate_tool_call_valid(self) -> None:
        # Valid get_events
        validate_tool_call("get_events", {
            "type": "adas_disengagement",
            "start": "2026-10-27",
            "end": "2026-10-27",
        })

        # Valid trend
        validate_tool_call("trend", {
            "metric": "range_per_charge",
            "start": "2026-10-01",
            "end": "2026-10-28",
            "granularity": "day",
        })

        # Valid explain_change
        validate_tool_call("explain_change", {
            "metric": "range_per_charge",
            "window_a": "2026-10-01/2026-10-07",
            "window_b": "2026-10-22/2026-10-28",
        })

        # Valid timeline_before
        validate_tool_call("timeline_before", {
            "event_type": "battery_overtemp_warning",
            "seconds_before": 600,
        })

        # Valid lookup_dtc
        validate_tool_call("lookup_dtc", {
            "code": "P0A7E",
        })

    def test_validate_tool_call_invalid(self) -> None:
        # Missing required parameter
        with pytest.raises(jsonschema.ValidationError):
            validate_tool_call("trend", {
                "metric": "range_per_charge",
                "start": "2026-10-01",
                # missing end
            })

        # Invalid event_type enum
        with pytest.raises(jsonschema.ValidationError):
            validate_tool_call("get_events", {
                "type": "non_existent_event_type_123",
                "start": "2026-10-01",
                "end": "2026-10-02",
            })

    def test_evidence_packet_schema_validation(self) -> None:
        packet = make_evidence_packet(
            tool="trend",
            query_type="metric_trend",
            time_range=["2026-10-01", "2026-10-28"],
            findings=[
                {
                    "id": "f1",
                    "claim": "range_per_charge declined 38.5% over the 4-week period",
                    "value": -38.5,
                    "unit": "%",
                    "contribution_pct": None,
                    "relation": "observation",
                    "confidence": 0.95,
                    "timestamps": [1790793000000, 1793212200000],
                }
            ],
            evidence_refs=["digest_daily:range_per_charge"],
            latency_ms=12,
        )
        assert packet["packet_id"].startswith("ev_")
        assert len(packet["findings"]) == 1
        validate_evidence_packet(packet)

    def test_dispatch_unknown_signal_returns_data_gap(self) -> None:
        res = dispatch_tool(
            tool_name="trend",
            args={"metric": "unknown_metric_12345", "start": "2026-10-01", "end": "2026-10-07"},
            db_path="data/vehicle.db",
        )
        assert len(res["data_gaps"]) >= 1
        assert res["data_gaps"][0]["reason"] == "signal_unknown"
