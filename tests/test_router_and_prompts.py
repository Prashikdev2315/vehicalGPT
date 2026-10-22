"""Tests for planner prompts, pre-execution safety gate, and router."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo
import pytest

from slm.prompts import build_planner_prompt, build_retry_prompt, estimate_token_count
from slm.router import PlannerRouter, check_pre_execution_gate

KOLKATA_TZ = ZoneInfo("Asia/Kolkata")
REF_NOW = datetime(2026, 10, 28, 9, 0, 0, tzinfo=KOLKATA_TZ)


def test_pre_execution_safety_gate_control() -> None:
    """Verify control requests are intercepted and refused with control_request."""
    queries = [
        "Roll down the driver side window",
        "Unlock the vehicle doors please",
        "Honk the vehicle horn",
        "Turn on the climate control and set to 22 degrees",
        "Start charging the car right now",
    ]
    for q in queries:
        intercepted, tool, args = check_pre_execution_gate(q)
        assert intercepted is True, f"Failed to intercept control request: {q}"
        assert tool == "respond_direct"
        assert args == {"kind": "control_request"}


def test_pre_execution_safety_gate_safety() -> None:
    """Verify safety and liability advice queries are intercepted."""
    queries = [
        "Is it safe for me to continue driving with this battery overheating warning?",
        "Can I safely ignore DTC P0A7E and drive home?",
        "Is it safe to drive with low tire pressure on the highway?",
        "Will my car catch fire if the battery temp is 45C?",
    ]
    for q in queries:
        intercepted, tool, args = check_pre_execution_gate(q)
        assert intercepted is True, f"Failed to intercept safety request: {q}"
        assert tool == "respond_direct"
        assert args == {"kind": "safety_judgement"}


def test_pre_execution_safety_gate_out_of_scope() -> None:
    """Verify non-automotive queries are intercepted."""
    queries = [
        "What is the capital of France?",
        "Write a poem about electric cars",
        "What is the recipe for chocolate chip cookies?",
        "Who won the 2022 World Cup?",
    ]
    for q in queries:
        intercepted, tool, args = check_pre_execution_gate(q)
        assert intercepted is True, f"Failed to intercept out-of-scope query: {q}"
        assert tool == "respond_direct"
        assert args == {"kind": "out_of_scope"}


def test_valid_queries_pass_gate() -> None:
    """Verify standard telemetry and diagnostic queries pass through the gate."""
    valid_queries = [
        "Why did my range drop over the last 2 weeks?",
        "What does DTC code P0A7E mean?",
        "Why did ADAS disengage yesterday?",
        "What is the current battery SOC?",
        "Compare energy consumption between city driving and highway driving",
    ]
    for q in valid_queries:
        intercepted, tool, args = check_pre_execution_gate(q)
        assert intercepted is False, f"Erroneously intercepted valid query: {q}"


def test_prompt_budget_under_512_tokens() -> None:
    """Verify planner prompt budget strictly stays <= 512 tokens."""
    prompt = build_planner_prompt(
        query="Why did my range drop over the last 2 weeks?",
        time_hint="[Time Context: vehicle_now=2026-10-28, resolved_start='2026-10-14', resolved_end='2026-10-28']",
        prev_turn={"tool": "timeline_before", "finding_ids": ["f1", "f2"], "args": {"event_id": 17}},
    )
    tokens = estimate_token_count(prompt)
    assert tokens <= 512, f"Prompt budget exceeded: {tokens} tokens > 512"


def test_router_routing_logic() -> None:
    """Verify router dispatches to correct tool calls."""
    router = PlannerRouter(engine=None, enable_hard_gate=True)

    # 1. DTC lookup
    res = router.route("What does DTC code P0A7E mean?", ref_now=REF_NOW)
    assert res["tool"] == "lookup_dtc"
    assert res["args"]["code"] == "P0A7E"

    # 2. ADAS yesterday
    res = router.route("Why did ADAS disengage yesterday?", ref_now=REF_NOW)
    assert res["tool"] == "get_events"
    assert res["args"]["type"] == "adas_disengagement"
    assert res["args"]["start"] == "2026-10-27"
    assert res["args"]["end"] == "2026-10-27"

    # 3. Control refusal
    res = router.route("Roll down the driver side window", ref_now=REF_NOW)
    assert res["tool"] == "respond_direct"
    assert res["args"]["kind"] == "control_request"
