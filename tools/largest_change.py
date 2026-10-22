"""Implementation of largest_change tool (change-point detection)."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from insight.change_point import detect_largest_change_point
from store.ro_db import get_readonly_connection
from tools.base import make_error_packet, make_evidence_packet
from tools.registry import get_signal_unit, normalize_signal_name, register_tool
from tools.time_parser import parse_iso_to_epoch_ms


@register_tool("largest_change")
def handle_largest_change(args: dict[str, Any], db_path: Path | str) -> dict[str, Any]:
    """Find the point in time when the largest sustained change occurred for a metric.

    Args:
        args: {'metric': str, 'start': iso_date, 'end': iso_date, 'direction': 'drop' | 'rise' | 'either'}
        db_path: Path to vehicle database.
    """
    t0 = time.perf_counter()
    raw_metric = args["metric"]
    canonical = normalize_signal_name(raw_metric)
    start_iso = args["start"]
    end_iso = args["end"]
    direction = args.get("direction", "drop")

    if not canonical:
        return make_error_packet(
            tool="largest_change",
            query_type="change_point_detection",
            time_range=[start_iso, end_iso],
            reason="signal_unknown",
            detail=f"Unknown metric or signal: '{raw_metric}'",
            latency_ms=int((time.perf_counter() - t0) * 1000),
        )

    start_ms = parse_iso_to_epoch_ms(start_iso, end_of_day=False)
    end_ms = parse_iso_to_epoch_ms(end_iso, end_of_day=True)

    conn = get_readonly_connection(db_path)
    cur = conn.cursor()

    dates: list[str] = []
    values: list[float] = []
    timestamps: list[int] = []
    evidence_refs: list[str] = []

    # Check digest_daily first for daily metrics
    rows = cur.execute(
        """
        SELECT day, value FROM digest_daily
        WHERE metric = ? AND day >= ? AND day <= ?
        ORDER BY day ASC
        """,
        (canonical, start_iso, end_iso),
    ).fetchall()

    if rows and len(rows) >= 4:
        for r in rows:
            dates.append(r["day"])
            values.append(r["value"])
            timestamps.append(parse_iso_to_epoch_ms(r["day"], end_of_day=False))
        evidence_refs.append(f"digest_daily:{canonical}")
    else:
        # Fall back to trips table if metric is efficiency or trips
        if canonical in ("energy_per_km", "fuel_efficiency", "mileage", "efficiency"):
            t_rows = cur.execute(
                """
                SELECT id, ts_start, (energy_kwh * 1000.0 / distance_km) AS epk
                FROM trips
                WHERE ts_start >= ? AND ts_end <= ? AND distance_km > 0.5
                ORDER BY ts_start ASC
                """,
                (start_ms, end_ms),
            ).fetchall()
            for r in t_rows:
                from datetime import datetime, timezone
                d_str = datetime.fromtimestamp(r["ts_start"] / 1000.0, tz=timezone.utc).strftime("%Y-%m-%d")
                dates.append(d_str)
                values.append(r["epk"])
                timestamps.append(r["ts_start"])
                evidence_refs.append(f"trip:{r['id']}")

    conn.close()
    latency_ms = int((time.perf_counter() - t0) * 1000)

    if len(values) < 4:
        return make_evidence_packet(
            tool="largest_change",
            query_type="change_point_detection",
            time_range=[start_iso, end_iso],
            findings=[],
            evidence_refs=[],
            data_gaps=[{
                "reason": "no_events_found",
                "detail": f"Insufficient data points (n={len(values)}) to detect change point between {start_iso} and {end_iso}",
            }],
            latency_ms=latency_ms,
        )

    res = detect_largest_change_point(dates, values, timestamps, direction=direction, min_window=2)
    if not res:
        return make_evidence_packet(
            tool="largest_change",
            query_type="change_point_detection",
            time_range=[start_iso, end_iso],
            findings=[],
            evidence_refs=evidence_refs[:10],
            data_gaps=[{
                "reason": "no_events_found",
                "detail": "No statistically significant change point found in the specified window",
            }],
            latency_ms=latency_ms,
        )

    unit = get_signal_unit(canonical)
    chg_date = res["date"]
    delta = res["delta"]
    pct = res["pct_change"]
    dir_word = "dropped" if delta < 0 else "rose"

    findings = [
        {
            "id": "f1",
            "claim": f"Largest sustained {canonical} {direction} occurred around {chg_date}: shifted {abs(pct):.1f}% ({dir_word} from {res['mean_before']} to {res['mean_after']} {unit})",
            "value": round(pct, 2),
            "unit": "%",
            "contribution_pct": None,
            "relation": "observation",
            "confidence": res["confidence"],
            "timestamps": [res["timestamp"]],
        },
        {
            "id": "f2",
            "claim": f"Mean before change: {res['mean_before']} {unit} (n={res['n_before']}); mean after: {res['mean_after']} {unit} (n={res['n_after']}). Net shift: {delta:+.2f} {unit}.",
            "value": round(delta, 2),
            "unit": unit,
            "contribution_pct": None,
            "relation": "observation",
            "confidence": res["confidence"],
            "timestamps": [res["timestamp"]],
        },
    ]

    return make_evidence_packet(
        tool="largest_change",
        query_type="change_point_detection",
        time_range=[start_iso, end_iso],
        findings=findings,
        evidence_refs=evidence_refs[:10],
        display={"chart": "line", "series": [canonical]},
        latency_ms=latency_ms,
    )
