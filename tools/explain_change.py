"""Implementation of explain_change tool (attribution decomposition)."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from insight.attribution import decompose_metric_change
from tools.base import make_error_packet, make_evidence_packet
from tools.registry import get_signal_unit, normalize_signal_name, register_tool
from tools.time_parser import parse_iso_interval


@register_tool("explain_change")
def handle_explain_change(args: dict[str, Any], db_path: Path | str = "data/vehicle.db") -> dict[str, Any]:
    """Explain changes in a metric across two time windows using causal attribution decomposition.

    Args:
        args: {'metric': str, 'window_a': iso_interval, 'window_b': iso_interval}
        db_path: Path to SQLite vehicle database.
    """
    t0 = time.perf_counter()
    raw_metric = args.get("metric", "")
    canonical = normalize_signal_name(raw_metric)
    window_a_str = args.get("window_a", "")
    window_b_str = args.get("window_b", "")

    start_a_iso = window_a_str.split("/")[0] if "/" in window_a_str else window_a_str
    end_b_iso = window_b_str.split("/")[-1] if "/" in window_b_str else window_b_str
    time_range = [start_a_iso, end_b_iso]

    if not canonical:
        return make_error_packet(
            tool="explain_change",
            query_type="attribution_decomposition",
            time_range=time_range,
            reason="signal_unknown",
            detail=f"Unknown metric or signal: '{raw_metric}'",
            latency_ms=int((time.perf_counter() - t0) * 1000),
        )

    try:
        w_a_ms = parse_iso_interval(window_a_str)
        w_b_ms = parse_iso_interval(window_b_str)
    except Exception as e:
        return make_error_packet(
            tool="explain_change",
            query_type="attribution_decomposition",
            time_range=time_range,
            reason="signal_unknown",
            detail=f"Failed to parse intervals: {e}",
            latency_ms=int((time.perf_counter() - t0) * 1000),
        )

    res = decompose_metric_change(canonical, w_a_ms, w_b_ms, db_path=db_path)

    if "error" in res:
        return make_evidence_packet(
            tool="explain_change",
            query_type="attribution_decomposition",
            time_range=time_range,
            findings=[],
            evidence_refs=[],
            data_gaps=[{
                "reason": "no_events_found",
                "detail": res["error"],
            }],
            latency_ms=int((time.perf_counter() - t0) * 1000),
        )

    unit = get_signal_unit(canonical)
    delta = res["delta"]
    pct = res["pct_change"]
    dir_word = "dropped" if delta < 0 else "increased"

    findings: list[dict[str, Any]] = [
        {
            "id": "f1",
            "claim": (
                f"{canonical} {dir_word} by {abs(delta):.2f} {unit} ({abs(pct):.1f}%) "
                f"from {res['mean_a']:.2f} {unit} in window A to {res['mean_b']:.2f} {unit} in window B"
            ),
            "value": round(delta, 2),
            "unit": unit,
            "contribution_pct": None,
            "relation": "observation",
            "confidence": 0.95,
            "timestamps": [],
        }
    ]

    for idx, c in enumerate(res.get("causes", []), start=2):
        findings.append({
            "id": f"f{idx}",
            "claim": c["description"],
            "value": round(c["delta_value"], 2) if "delta_value" in c else None,
            "unit": unit,
            "contribution_pct": round(c["contribution_pct"], 1) if "contribution_pct" in c else None,
            "relation": c["relation"],
            "confidence": round(c["confidence"], 2),
            "timestamps": [],
        })

    latency_ms = int((time.perf_counter() - t0) * 1000)
    return make_evidence_packet(
        tool="explain_change",
        query_type="attribution_decomposition",
        time_range=time_range,
        findings=findings,
        unexplained_pct=res.get("unexplained_pct", 0.0),
        evidence_refs=res.get("evidence_refs", ["trips"])[:10],
        display={"chart": "bar", "series": [canonical]},
        latency_ms=latency_ms,
    )
