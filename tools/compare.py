"""Implementation of compare tool."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from insight.cohort import compare_cohort_statistics, filter_cohort_data
from store.ro_db import get_readonly_connection
from tools.base import make_error_packet, make_evidence_packet
from tools.registry import get_signal_unit, normalize_signal_name, register_tool
from tools.time_parser import parse_iso_to_epoch_ms


@register_tool("compare")
def handle_compare(args: dict[str, Any], db_path: Path | str) -> dict[str, Any]:
    """Compare a metric between two operational segments across a time range.

    Args:
        args: {'metric': str, 'segment_a': str, 'segment_b': str, 'start': iso_date, 'end': iso_date}
        db_path: Path to vehicle database.
    """
    t0 = time.perf_counter()
    raw_metric = args["metric"]
    canonical = normalize_signal_name(raw_metric)
    segment_a = args["segment_a"]
    segment_b = args["segment_b"]
    start_iso = args["start"]
    end_iso = args["end"]

    if not canonical:
        return make_error_packet(
            tool="compare",
            query_type="cohort_comparison",
            time_range=[start_iso, end_iso],
            reason="signal_unknown",
            detail=f"Unknown metric or signal: '{raw_metric}'",
            latency_ms=int((time.perf_counter() - t0) * 1000),
        )

    start_ms = parse_iso_to_epoch_ms(start_iso, end_of_day=False)
    end_ms = parse_iso_to_epoch_ms(end_iso, end_of_day=True)

    conn = get_readonly_connection(db_path)
    vals_a, refs_a = filter_cohort_data(conn, segment_a, canonical, start_ms, end_ms)
    vals_b, refs_b = filter_cohort_data(conn, segment_b, canonical, start_ms, end_ms)
    conn.close()

    unit = get_signal_unit(canonical)
    stats = compare_cohort_statistics(vals_a, vals_b)
    latency_ms = int((time.perf_counter() - t0) * 1000)

    if stats["mean_a"] is None or stats["mean_b"] is None:
        return make_evidence_packet(
            tool="compare",
            query_type="cohort_comparison",
            time_range=[start_iso, end_iso],
            findings=[],
            evidence_refs=[],
            data_gaps=[{
                "reason": "no_events_found",
                "detail": f"Insufficient trip data for segments '{segment_a}' (n={stats['n_a']}) or '{segment_b}' (n={stats['n_b']})",
            }],
            latency_ms=latency_ms,
        )

    gap = stats["gap"]
    pct_gap = stats["pct_gap"]
    dir_str = "higher" if gap > 0 else "lower"

    findings = [
        {
            "id": "f1",
            "claim": f"{canonical} in {segment_a} driving averaged {stats['mean_a']} {unit} vs {stats['mean_b']} {unit} in {segment_b} ({abs(pct_gap):.1f}% {dir_str})",
            "value": round(pct_gap, 2),
            "unit": "%",
            "contribution_pct": None,
            "relation": "observation",
            "confidence": stats["confidence"],
            "timestamps": [],
        },
        {
            "id": "f2",
            "claim": f"Sample size: {stats['n_a']} trips ({segment_a}), {stats['n_b']} trips ({segment_b}). Absolute difference: {gap:+.2f} {unit}.",
            "value": round(gap, 2),
            "unit": unit,
            "contribution_pct": None,
            "relation": "observation",
            "confidence": stats["confidence"],
            "timestamps": [],
        },
    ]

    evidence_refs = list(set(refs_a + refs_b))[:20]

    return make_evidence_packet(
        tool="compare",
        query_type="cohort_comparison",
        time_range=[start_iso, end_iso],
        findings=findings,
        evidence_refs=evidence_refs,
        display={"chart": "bar", "series": [segment_a, segment_b]},
        latency_ms=latency_ms,
    )
