"""Implementation of respond_direct tool."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from tools.base import make_evidence_packet
from tools.registry import register_tool

REFUSAL_TEMPLATES = {
    "control_request": "VehicleGPT is a read-only diagnostics assistant and cannot execute vehicle control commands (e.g. unlocking doors, altering speed, or modifying ECU parameters) due to functional safety isolation.",
    "safety_judgement": "Safety certifications, legal liability determinations, and driving fault judgements cannot be evaluated by on-board diagnostics tools.",
    "out_of_scope": "This request is outside the scope of vehicle diagnostics, telemetry analysis, and maintenance operations.",
    "clarify": "The query is ambiguous. Please specify the target metric, time window, or event type to analyze.",
}


@register_tool("respond_direct")
def handle_respond_direct(args: dict[str, Any], db_path: Path | str) -> dict[str, Any]:
    """Emit direct refusal or clarification without executing database queries.

    Args:
        args: {'kind': 'control_request' | 'safety_judgement' | 'out_of_scope' | 'clarify', 'clarify_field': optional}
        db_path: Ignored.
    """
    t0 = time.perf_counter()
    kind = args["kind"]
    clarify_field = args.get("clarify_field")

    msg = REFUSAL_TEMPLATES.get(kind, REFUSAL_TEMPLATES["out_of_scope"])
    if kind == "clarify" and clarify_field:
        msg = f"Please clarify the {clarify_field} for this query."

    findings = [{
        "id": "f1",
        "claim": msg,
        "value": None,
        "unit": None,
        "contribution_pct": None,
        "relation": "observation",
        "confidence": 1.0,
        "timestamps": [],
    }]

    latency_ms = int((time.perf_counter() - t0) * 1000)
    return make_evidence_packet(
        tool="respond_direct",
        query_type="direct_response",
        time_range=["2026-10-01", "2026-10-28"],
        findings=findings,
        evidence_refs=[],
        latency_ms=latency_ms,
    )
