"""Implementation of search_logs tool."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from store.ro_db import get_readonly_connection
from slm.sanitizer import sanitize_log_message
from tools.base import make_evidence_packet
from tools.registry import register_tool
from tools.time_parser import parse_iso_to_epoch_ms


@register_tool("search_logs")
def handle_search_logs(args: dict[str, Any], db_path: Path | str) -> dict[str, Any]:
    """Search system/QNX/Android logs by keyword or query across a time window.

    Args:
        args: {'query': str, 'start': iso_date, 'end': iso_date, 'source': optional, 'limit': optional}
        db_path: Path to vehicle database.
    """
    t0 = time.perf_counter()
    query_str = args["query"].strip()
    start_iso = args["start"]
    end_iso = args["end"]
    source = args.get("source")
    limit = min(int(args.get("limit", 20)), 100)

    start_ms = parse_iso_to_epoch_ms(start_iso, end_of_day=False)
    end_ms = parse_iso_to_epoch_ms(end_iso, end_of_day=True)

    conn = get_readonly_connection(db_path)
    cur = conn.cursor()

    sql = """
        SELECT l.id, l.ts, l.source, l.level, l.message
        FROM logs l
        WHERE l.ts >= ? AND l.ts <= ? AND l.message LIKE ?
    """
    params: list[Any] = [start_ms, end_ms, f"%{query_str}%"]

    if source:
        sql += " AND l.source = ?"
        params.append(source)

    sql += " ORDER BY l.ts ASC LIMIT ?"
    params.append(limit)

    rows = cur.execute(sql, params).fetchall()
    conn.close()

    latency_ms = int((time.perf_counter() - t0) * 1000)

    if not rows:
        return make_evidence_packet(
            tool="search_logs",
            query_type="log_search",
            time_range=[start_iso, end_iso],
            findings=[],
            evidence_refs=[],
            data_gaps=[{
                "reason": "no_events_found",
                "detail": f"No logs matching '{query_str}' found between {start_iso} and {end_iso}",
            }],
            latency_ms=latency_ms,
        )

    findings: list[dict[str, Any]] = []
    evidence_refs: list[str] = []
    timestamps: list[int] = []

    for r in rows:
        lid = r["id"]
        evidence_refs.append(f"log:{lid}")
        timestamps.append(r["ts"])

    # Create safe quoted representation of top matching messages (escaped and length capped)
    quoted_samples = " | ".join(
        f"[{r['source']}] {sanitize_log_message(r['message'], max_chars=120, wrap_snippet=False)}"
        for r in rows[:3]
    )
    findings.append({
        "id": "f1",
        "claim": f"Found {len(rows)} log entries matching '{query_str}'. Matches: {quoted_samples}",
        "value": float(len(rows)),
        "unit": "lines",
        "contribution_pct": None,
        "relation": "observation",
        "confidence": 1.0,
        "timestamps": timestamps,
    })

    return make_evidence_packet(
        tool="search_logs",
        query_type="log_search",
        time_range=[start_iso, end_iso],
        findings=findings,
        evidence_refs=evidence_refs,
        display={"chart": "table", "series": ["logs"]},
        latency_ms=latency_ms,
    )
