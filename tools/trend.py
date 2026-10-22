"""Implementation of trend tool."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any
import numpy as np

from store.ro_db import get_readonly_connection
from tools.base import make_error_packet, make_evidence_packet
from tools.registry import get_signal_unit, normalize_signal_name, register_tool
from tools.time_parser import parse_iso_to_epoch_ms


@register_tool("trend")
def handle_trend(args: dict[str, Any], db_path: Path | str) -> dict[str, Any]:
    """Analyze the trend and trajectory of a metric over time.

    Args:
        args: {'metric': str, 'start': iso_date, 'end': iso_date, 'granularity': 'trip' | 'day' | 'week'}
        db_path: Path to vehicle database.
    """
    t0 = time.perf_counter()
    raw_metric = args["metric"]
    canonical = normalize_signal_name(raw_metric)
    start_iso = args["start"]
    end_iso = args["end"]
    granularity = args.get("granularity", "day")

    if not canonical:
        return make_error_packet(
            tool="trend",
            query_type="metric_trend",
            time_range=[start_iso, end_iso],
            reason="signal_unknown",
            detail=f"Unknown metric: '{raw_metric}'",
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

    # 1. Daily digest path
    if granularity in ("day", "week") and canonical in ("range_per_charge", "energy_per_km"):
        rows = cur.execute(
            """
            SELECT day, value FROM digest_daily
            WHERE metric = ? AND day >= ? AND day <= ?
            ORDER BY day ASC
            """,
            (canonical, start_iso, end_iso),
        ).fetchall()
        for r in rows:
            dates.append(r["day"])
            values.append(r["value"])
            timestamps.append(parse_iso_to_epoch_ms(r["day"], end_of_day=False))
        evidence_refs.append(f"digest_daily:{canonical}")

    # 2. Trip-level path
    elif granularity == "trip" and canonical in ("energy_per_km", "fuel_efficiency", "mileage", "efficiency"):
        rows = cur.execute(
            """
            SELECT id, ts_start, (energy_kwh * 1000.0 / distance_km) AS epk
            FROM trips
            WHERE ts_start >= ? AND ts_end <= ? AND distance_km > 0.5
            ORDER BY ts_start ASC
            """,
            (start_ms, end_ms),
        ).fetchall()
        for r in rows:
            from datetime import datetime, timezone
            d_str = datetime.fromtimestamp(r["ts_start"] / 1000.0, tz=timezone.utc).strftime("%Y-%m-%d")
            dates.append(d_str)
            values.append(r["epk"])
            timestamps.append(r["ts_start"])
            evidence_refs.append(f"trip:{r['id']}")

    # 3. Generic signal path from signals_1m or signals
    else:
        rows = cur.execute(
            """
            SELECT ts, avg FROM signals_1m
            WHERE signal = ? AND ts >= ? AND ts <= ?
            ORDER BY ts ASC
            """,
            (canonical, start_ms, end_ms),
        ).fetchall()
        for r in rows:
            from datetime import datetime, timezone
            d_str = datetime.fromtimestamp(r["ts"] / 1000.0, tz=timezone.utc).strftime("%Y-%m-%d")
            dates.append(d_str)
            values.append(r["avg"])
            timestamps.append(r["ts"])
        evidence_refs.append(f"signals_1m:{canonical}")

    conn.close()
    latency_ms = int((time.perf_counter() - t0) * 1000)

    if not values:
        return make_evidence_packet(
            tool="trend",
            query_type="metric_trend",
            time_range=[start_iso, end_iso],
            findings=[],
            evidence_refs=[],
            data_gaps=[{
                "reason": "no_events_found",
                "detail": f"No data points found for '{canonical}' between {start_iso} and {end_iso}",
            }],
            latency_ms=latency_ms,
        )

    y = np.array(values, dtype=float)
    unit = get_signal_unit(canonical)
    mean_val = float(np.mean(y))
    min_val = float(np.min(y))
    max_val = float(np.max(y))
    first_val = float(y[0])
    last_val = float(y[-1])
    delta = last_val - first_val
    pct_change = (delta / first_val * 100.0) if abs(first_val) > 1e-6 else 0.0

    # Linear slope
    x = np.arange(len(y), dtype=float)
    if len(y) > 1:
        slope, intercept = np.polyfit(x, y, 1)
    else:
        slope = 0.0

    dir_desc = "declined" if delta < -1.0 else ("rose" if delta > 1.0 else "remained steady")

    findings = [
        {
            "id": "f1",
            "claim": f"{canonical} {dir_desc} by {abs(pct_change):.1f}% over the period ({first_val:.1f} to {last_val:.1f} {unit})",
            "value": round(pct_change, 2),
            "unit": "%",
            "contribution_pct": None,
            "relation": "observation",
            "confidence": 0.95,
            "timestamps": [timestamps[0], timestamps[-1]],
        },
        {
            "id": "f2",
            "claim": f"Period statistics: mean {mean_val:.1f} {unit}, min {min_val:.1f} {unit}, max {max_val:.1f} {unit} across {len(values)} {granularity} samples.",
            "value": round(mean_val, 2),
            "unit": unit,
            "contribution_pct": None,
            "relation": "observation",
            "confidence": 1.0,
            "timestamps": [timestamps[0], timestamps[-1]],
        },
    ]

    return make_evidence_packet(
        tool="trend",
        query_type="metric_trend",
        time_range=[start_iso, end_iso],
        findings=findings,
        evidence_refs=evidence_refs[:15],
        display={"chart": "line", "series": [canonical]},
        latency_ms=latency_ms,
    )
