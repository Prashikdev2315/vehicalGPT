"""Implementation of get_events tool."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from store.ro_db import get_readonly_connection
from tools.base import make_evidence_packet
from tools.registry import register_tool
from tools.time_parser import parse_iso_to_epoch_ms


@register_tool("get_events")
def handle_get_events(args: dict[str, Any], db_path: Path | str) -> dict[str, Any]:
    """Retrieve discrete events filtered by type, time range, and optional source.

    Args:
        args: {'type': event_type, 'start': iso_date, 'end': iso_date, 'source': optional, 'limit': optional}
        db_path: Path to vehicle database.
    """
    t0 = time.perf_counter()
    event_type = args["type"]
    start_iso = args["start"]
    end_iso = args["end"]
    source = args.get("source")
    limit = min(int(args.get("limit", 50)), 200)

    start_ms = parse_iso_to_epoch_ms(start_iso, end_of_day=False)
    end_ms = parse_iso_to_epoch_ms(end_iso, end_of_day=True)

    conn = get_readonly_connection(db_path)
    cur = conn.cursor()

    query = """
        SELECT e.id, e.ts_start, e.ts_end, e.type, e.source, e.severity, e.payload, e.trip_id
        FROM events e
        WHERE e.ts_start >= ? AND e.ts_start <= ?
    """
    params: list[Any] = [start_ms, end_ms]

    if event_type != "any":
        query += " AND e.type = ?"
        params.append(event_type)

    if source:
        query += " AND e.source = ?"
        params.append(source)

    query += " ORDER BY e.ts_start ASC LIMIT ?"
    params.append(limit)

    rows = cur.execute(query, params).fetchall()

    # Query clip refs if any
    event_ids = [r["id"] for r in rows]
    clips_by_event: dict[int, list[int]] = {}
    if event_ids:
        placeholders = ",".join("?" for _ in event_ids)
        clip_rows = cur.execute(
            f"SELECT event_id, id FROM clip_refs WHERE event_id IN ({placeholders})",
            event_ids,
        ).fetchall()
        for cr in clip_rows:
            clips_by_event.setdefault(cr["event_id"], []).append(cr["id"])

    conn.close()

    events_list: list[dict[str, Any]] = []
    evidence_refs: list[str] = []
    reason_counts: dict[str, int] = {}

    for r in rows:
        eid = r["id"]
        evidence_refs.append(f"event:{eid}")
        summary = f"{r['type']} ({r['severity']})"
        if r["payload"]:
            try:
                p_dict = json.loads(r["payload"]) if isinstance(r["payload"], str) else r["payload"]
                if "reason" in p_dict:
                    r_text = p_dict["reason"]
                    reason_counts[r_text] = reason_counts.get(r_text, 0) + 1
                    summary += f": {r_text}"
                elif "reason_text" in p_dict:
                    r_text = p_dict["reason_text"]
                    reason_counts[r_text] = reason_counts.get(r_text, 0) + 1
                    summary += f": {r_text}"
            except Exception:
                pass

        evt_item: dict[str, Any] = {
            "event_id": eid,
            "type": r["type"],
            "ts_start": r["ts_start"],
            "severity": r["severity"],
            "summary": summary,
        }
        if r["ts_end"] is not None:
            evt_item["ts_end"] = r["ts_end"]
        if eid in clips_by_event:
            evt_item["clip_refs"] = clips_by_event[eid]

        events_list.append(evt_item)

    latency_ms = int((time.perf_counter() - t0) * 1000)

    if not events_list:
        return make_evidence_packet(
            tool="get_events",
            query_type="events_lookup",
            time_range=[start_iso, end_iso],
            findings=[],
            events=[],
            evidence_refs=[],
            data_gaps=[{
                "reason": "no_events_found",
                "detail": f"No events of type '{event_type}' found between {start_iso} and {end_iso}",
            }],
            latency_ms=latency_ms,
        )

    # Findings
    findings: list[dict[str, Any]] = [
        {
            "id": "f1",
            "claim": f"Found {len(events_list)} {event_type} event(s) between {start_iso} and {end_iso}",
            "value": float(len(events_list)),
            "unit": "events",
            "contribution_pct": None,
            "relation": "observation",
            "confidence": 1.0,
            "timestamps": [e["ts_start"] for e in events_list],
        }
    ]

    # Additional breakdown finding if reasons were present
    if reason_counts:
        top_reasons = ", ".join(f"{k} ({v})" for k, v in sorted(reason_counts.items(), key=lambda x: -x[1]))
        findings.append({
            "id": "f2",
            "claim": f"Primary disengagement causes: {top_reasons}",
            "value": None,
            "unit": None,
            "contribution_pct": None,
            "relation": "observation",
            "confidence": 1.0,
            "timestamps": [e["ts_start"] for e in events_list],
        })

    return make_evidence_packet(
        tool="get_events",
        query_type="events_lookup",
        time_range=[start_iso, end_iso],
        findings=findings,
        events=events_list,
        evidence_refs=evidence_refs,
        display={"chart": "timeline", "series": ["events"]},
        latency_ms=latency_ms,
    )
