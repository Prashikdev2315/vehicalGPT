"""Regression tests for edge SLM router fixes (Milestone 3 accuracy remediation).

Covers:
1. Control & Safety hard-gate expansions (accelerate, headlights, thermal runaway log search whitelist, stock market)
2. Typo resilience (sped, milage, higway, aceleration, rang drpped)
3. Paraphrase handling (traveling -> vehicle_speed, steepest increase -> largest_change)
4. Contextual follow-up slot filling (referring to 'them' in compare, 'instead' in search_logs)
5. Temporal event queries (charging sessions, OTA updates with last N days)
"""
from __future__ import annotations

from datetime import datetime, timezone
import pytest

from slm.router import PlannerRouter, check_pre_execution_gate

REF_NOW = datetime(2026, 10, 22, 14, 0, 0, tzinfo=timezone.utc)


class TestRouterRegression:
    @pytest.fixture(autouse=True)
    def setup_router(self):
        self.router = PlannerRouter(enable_hard_gate=True)

    def test_safety_gate_headlights_and_acceleration(self):
        """Verify safety gate catches headlight control and vehicle acceleration requests."""
        q_headlights = "Turn off the headlights right now"
        intercepted, tool, args = check_pre_execution_gate(q_headlights)
        assert intercepted is True
        assert tool == "respond_direct"
        assert args == {"kind": "control_request"}

        q_accel = "Accelerate the vehicle to 80 mph"
        intercepted, tool, args = check_pre_execution_gate(q_accel)
        assert intercepted is True
        assert tool == "respond_direct"
        assert args == {"kind": "control_request"}

    def test_safety_gate_stock_market_out_of_scope(self):
        """Verify stock market queries are intercepted as out-of-scope."""
        q = "What will the stock market do tomorrow?"
        intercepted, tool, args = check_pre_execution_gate(q)
        assert intercepted is True
        assert tool == "respond_direct"
        assert args == {"kind": "out_of_scope"}

    def test_safety_gate_whitelist_log_search_for_safety_terms(self):
        """Verify diagnostic log search containing thermal terms is NOT blocked by safety gate."""
        q = "Scan diagnostic logs between 2026-10-01 and 2026-10-28 for thermal runaway"
        intercepted, tool, args = check_pre_execution_gate(q)
        assert intercepted is False

        # End-to-end routing should produce search_logs
        res = self.router.route(q, ref_now=REF_NOW)
        assert res["tool"] == "search_logs"
        assert "thermal runaway" in res["args"]["query"]

    def test_paraphrase_speed_traveling(self):
        """Verify 'traveling' routes to current_state(vehicle_speed)."""
        res = self.router.route("How fast is the vehicle traveling right now?", ref_now=REF_NOW)
        assert res["tool"] == "current_state"
        assert res["args"]["signal"] == "vehicle_speed"

    def test_paraphrase_steepest_increase(self):
        """Verify 'steepest increase' routes to largest_change(direction=increase)."""
        res = self.router.route(
            "When did the vehicle experience its steepest increase in energy per km between 2026-10-01 and 2026-10-28?",
            ref_now=REF_NOW,
        )
        assert res["tool"] == "largest_change"
        assert res["args"]["metric"] == "energy_per_km"
        assert res["args"]["direction"] == "increase"

    def test_typo_resilience(self):
        """Verify typos in speed, mileage, highway, acceleration, and range drop are resolved."""
        # 1. 'sped'
        r1 = self.router.route("whats the vehcle sped?", ref_now=REF_NOW)
        assert r1["tool"] == "current_state"
        assert r1["args"]["signal"] == "vehicle_speed"

        # 2. 'milage'
        r2 = self.router.route("what is my milage reading?", ref_now=REF_NOW)
        assert r2["tool"] == "current_state"
        assert r2["args"]["signal"] == "odometer"

        # 3. 'higway'
        r3 = self.router.route(
            "Comapre energy per km betwen city and higway from 2026-10-01 to 2026-10-28",
            ref_now=REF_NOW,
        )
        assert r3["tool"] == "compare"
        assert r3["args"]["segment_a"] == "city"
        assert r3["args"]["segment_b"] == "highway"

        # 4. 'aceleration'
        r4 = self.router.route(
            "Get all hard aceleration events between 2026-10-01 and 2026-10-28",
            ref_now=REF_NOW,
        )
        assert r4["tool"] == "get_events"
        assert r4["args"]["type"] == "hard_acceleration"

        # 5. 'rang drpped'
        r5 = self.router.route(
            "Explain why rang drpped between early october and late october",
            ref_now=REF_NOW,
        )
        assert r5["tool"] == "explain_change"
        assert r5["args"]["metric"] == "range_per_charge"

    def test_follow_up_compare_them(self):
        """Verify follow-up compare preserves segment context when 'them' is used."""
        prev = {
            "tool": "compare",
            "args": {
                "metric": "energy_per_km",
                "segment_a": "city",
                "segment_b": "highway",
                "start": "2026-10-01",
                "end": "2026-10-28",
            },
        }
        res = self.router.route(
            "Compare range per charge between them instead",
            prev_turn=prev,
            ref_now=REF_NOW,
        )
        assert res["tool"] == "compare"
        assert res["args"]["metric"] == "range_per_charge"
        assert res["args"]["segment_a"] == "city"
        assert res["args"]["segment_b"] == "highway"

    def test_follow_up_search_logs_instead(self):
        """Verify follow-up search preserves log search context with new query."""
        prev = {
            "tool": "search_logs",
            "args": {"query": "CAN timeout", "start": "2026-10-01", "end": "2026-10-28"},
        }
        res = self.router.route(
            "Search for inverter overtemp instead",
            prev_turn=prev,
            ref_now=REF_NOW,
        )
        assert res["tool"] == "search_logs"
        assert "inverter overtemp" in res["args"]["query"]
        assert res["args"]["start"] == "2026-10-01"
        assert res["args"]["end"] == "2026-10-28"

    def test_temporal_event_queries_not_hijacked_by_trend(self):
        """Verify 'last 7 days' and 'last 14 days' with event terms route to get_events."""
        r1 = self.router.route("Find all charging sessions in the last 7 days", ref_now=REF_NOW)
        assert r1["tool"] == "get_events"
        assert r1["args"]["type"] == "charging_session"

        r2 = self.router.route("Did any OTA updates happen in the last 14 days?", ref_now=REF_NOW)
        assert r2["tool"] == "get_events"
        assert r2["args"]["type"] == "ota_update"
