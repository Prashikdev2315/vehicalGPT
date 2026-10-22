"""Prompt templates and budget enforcement for VehicleGPT SLM Planner."""
from __future__ import annotations

import json
from typing import Any

# System prompt prefix defining role, available tools, catalog rules, and date context
SYSTEM_PROMPT_PREFIX = """<|im_start|>system
You are the VehicleGPT On-Board Diagnostics Planner.
Given a user query and time context, select the single best tool from:
- explain_change(metric, window_a, window_b)
- largest_change(metric, start, end, direction)
- get_events(type, start, end, source)
- timeline_before(event_id, event_type, occurrence, seconds_before)
- compare(metric, segment_a, segment_b, start, end)
- lookup_dtc(code)
- search_logs(query, start, end, source)
- current_state(signal)
- trend(metric, start, end, granularity)
- respond_direct(kind, clarify_field)

Rules:
1. Always output ONLY a JSON object: {"tool": "<name>", "args": {<params>}}.
2. Use EXACT date strings provided in the [Time Context]. Never alter or calculate dates.
3. Canonical metrics: energy_per_km, range_per_charge, soc, pack_temp, coolant_temp, coolant_pump_duty, tire_pressure_fl.
4. If the query asks for vehicle control, safety advice, or out-of-scope topics, emit respond_direct.<|im_end|>
"""

MAX_PROMPT_TOKENS = 512


def estimate_token_count(text: str) -> int:
    """Rough conservative estimate of token count (1 token ≈ 4 characters)."""
    return len(text) // 4 + 1


def build_planner_prompt(
    query: str,
    time_hint: str,
    prev_turn: dict[str, Any] | None = None,
) -> str:
    """Assemble planner prompt with system prefix, time hints, and compressed follow-up context.

    Ensures prompt budget strictly stays <= 512 tokens.
    """
    context_parts = [time_hint]

    # Compress follow-up context to previous tool call + finding IDs only (no large evidence tables)
    if prev_turn:
        prev_tool = prev_turn.get("tool")
        finding_ids = prev_turn.get("finding_ids", [])
        args_summary = prev_turn.get("args", {})
        context_parts.append(
            f"[Previous Context: tool={prev_tool}, args={json.dumps(args_summary)}, findings={finding_ids}]"
        )

    context_str = "\n".join(context_parts)
    user_turn = f"<|im_start|>user\n{context_str}\nQuery: {query}<|im_end|>\n<|im_start|>assistant\n"

    full_prompt = SYSTEM_PROMPT_PREFIX + user_turn

    # Verify prompt budget
    tok_est = estimate_token_count(full_prompt)
    if tok_est > MAX_PROMPT_TOKENS:
        # Truncate user turn query if excessively long
        trimmed_query = query[: 4 * (MAX_PROMPT_TOKENS - estimate_token_count(SYSTEM_PROMPT_PREFIX) - 50)]
        user_turn = f"<|im_start|>user\n{context_str}\nQuery: {trimmed_query}<|im_end|>\n<|im_start|>assistant\n"
        full_prompt = SYSTEM_PROMPT_PREFIX + user_turn

    return full_prompt


def build_retry_prompt(original_prompt: str, error_message: str) -> str:
    """Append schema validation diagnostic to prompt for single retry attempt."""
    retry_note = f"\n[Validation Error: {error_message}. Please correct the tool parameters and retry.]\n<|im_start|>assistant\n"
    return original_prompt.rstrip() + retry_note
