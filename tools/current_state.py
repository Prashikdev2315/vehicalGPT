"""Implementation of current_state tool."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from store.ro_db import get_readonly_connection
from tools.base import make_error_packet, make_evidence_packet
from tools.registry import get_signal_unit, normalize_signal_name, register_tool


@register_tool("current_state")
def handle_current_state(args: dict[str, Any], db_path: Path | str) -> dict[str, Any]:
    """Retrieve the latest value of a signal or metric.

    Args:
        args: {'signal': 'soc'}
        db_path: Path to vehicle database.
    """
    t0 = time.perf_counter()
    raw_signal = args["signal"]
    canonical = normalize_signal_name(raw_signal)

    if not canonical:
        return make_error_packet(
            tool="current_state",
            query_type="signal_latest",
            time_range=["2026-10-01", "2026-10-28"],
            reason="signal_unknown",
            detail=f"Unknown signal: '{raw_signal}'",
            latency_ms=int((time.perf_counter() - t0) * 1000),
        )

    conn = get_readonly_connection(db_path)
    cur = conn.cursor()

    # If derived metric like range_per_charge or energy_per_km, check digest_daily
    if canonical in ("range_per_charge", "energy_per_km"):
        d_row = cur.execute(
            "SELECT day, value FROM digest_daily WHERE metric = ? ORDER BY day DESC LIMIT 1",
            (canonical,),
        ).fetchone()
        if d_row:
            from tools.time_parser import parse_iso_to_epoch_ms
            ts_ms = parse_iso_to_epoch_ms(d_row["day"], end_of_day=True)
            val = d_row["value"]
            unit = get_signal_unit(canonical)
            conn.close()
            latency_ms = int((time.perf_counter() - t0) * 1000)
            return make_evidence_packet(
                tool="current_state",
                query_type="signal_latest",
                time_range=[d_row["day"], d_row["day"]],
                findings=[{
                    "id": "f1",
                    "claim": f"Latest {canonical} value is {val:.2f} {unit} on {d_row['day']}",
                    "value": round(val, 2),
                    "unit": unit,
                    "contribution_pct": None,
                    "relation": "observation",
                    "confidence": 1.0,
                    "timestamps": [ts_ms],
                }],
                evidence_refs=[f"digest_daily:{canonical}"],
                latency_ms=latency_ms,
            )

    # First check raw signals table
    row = cur.execute(
        "SELECT ts, value, unit FROM signals WHERE signal = ? ORDER BY ts DESC LIMIT 1",
        (canonical,),
    ).fetchone()

    # Fallback to signals_1s aggregate table
    if not row:
        row = cur.execute(
            "SELECT ts, avg AS value FROM signals_1s WHERE signal = ? ORDER BY ts DESC LIMIT 1",
            (canonical,),
        ).fetchone()
        if d_row:
            from tools.time_parser import parse_iso_to_epoch_ms
            ts_ms = parse_iso_to_epoch_ms(d_row["day"], end_of_day=True)
            val = d_row["value"]
            unit = get_signal_unit(canonical)
            conn.close()
            latency_ms = int((time.perf_counter() - t0) * 1000)
            return make_evidence_packet(
                tool="current_state",
                query_type="signal_latest",
                time_range=[d_row["day"], d_row["day"]],
                findings=[{
                    "id": "f1",
                    "claim": f"Latest {canonical} value is {val:.2f} {unit} on {d_row['day']}",
                    "value": round(val, 2),
                    "unit": unit,
                    "contribution_pct": None,
                    "relation": "observation",
                    "confidence": 1.0,
                    "timestamps": [ts_ms],
                }],
                evidence_refs=[f"digest_daily:{canonical}"],
                latency_ms=latency_ms,
            )

    conn.close()
    latency_ms = int((time.perf_counter() - t0) * 1000)

    if not row:
        return make_error_packet(
            tool="current_state",
            query_type="signal_latest",
            time_range=["2026-10-01", "2026-10-28"],
            reason="source_missing",
            detail=f"No telemetry data logged for signal '{canonical}'",
            latency_ms=latency_ms,
        )

    ts_val = row["ts"]
    val = row["value"]
    unit = row["unit"] if "unit" in row.keys() else get_signal_unit(canonical)

    findings = [{
        "id": "f1",
        "claim": f"Current value for {canonical} is {val:.2f} {unit} at timestamp {ts_val}",
        "value": round(val, 2),
        "unit": unit,
        "contribution_pct": None,
        "relation": "observation",
        "confidence": 1.0,
        "timestamps": [ts_val],
    }]

    return make_evidence_packet(
        tool="current_state",
        query_type="signal_latest",
        time_range=["2026-10-01", "2026-10-28"],
        findings=findings,
        evidence_refs=[f"signal:{canonical}"],
        latency_ms=latency_ms,
    )
