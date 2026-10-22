"""Timeline Before tool: Precursor deviation onset sequencing before vehicle events."""
from __future__ import annotations

import datetime
import json
import time
from typing import Any

from insight.timeline import detect_signal_deviation_onset
from store.ro_db import get_readonly_connection
from tools.base import make_error_packet, make_evidence_packet
from tools.registry import get_signal_unit, register_tool


@register_tool("timeline_before")
def handle_timeline_before(args: dict[str, Any], db_path: str = "data/vehicle.db") -> dict[str, Any]:
    """Retrieve multi-tier lookback data and sequence precursor signal deviations."""
    t0 = time.perf_counter()
    event_id = args.get("event_id")
    event_type = args.get("event_type")
    occurrence = args.get("occurrence", "latest")
    seconds_before = int(args.get("seconds_before", 600))

    if not event_id and not event_type:
        return make_error_packet(
            tool="timeline_before",
            query_type="precursor_timeline",
            time_range=["2026-10-01", "2026-10-28"],
            reason="signal_unknown",
            detail="Either event_id or event_type must be specified.",
            latency_ms=int((time.perf_counter() - t0) * 1000),
        )

    with get_readonly_connection(db_path) as conn:
        cur = conn.cursor()

        # Find target event
        if event_id is not None:
            cur.execute(
                "SELECT id, ts_start, ts_end, type, severity, payload FROM events WHERE id = ?",
                (event_id,),
            )
            row = cur.fetchone()
        else:
            order_clause = "DESC" if occurrence == "latest" else "ASC"
            cur.execute(
                f"SELECT id, ts_start, ts_end, type, severity, payload FROM events WHERE type = ? ORDER BY ts_start {order_clause} LIMIT 1",
                (event_type,),
            )
            row = cur.fetchone()

        if not row:
            return make_evidence_packet(
                tool="timeline_before",
                query_type="precursor_timeline",
                time_range=["2026-10-01", "2026-10-28"],
                findings=[],
                events=[],
                evidence_refs=[],
                data_gaps=[{
                    "reason": "no_events_found",
                    "detail": f"No event found matching criteria: id={event_id}, type={event_type}",
                }],
                latency_ms=int((time.perf_counter() - t0) * 1000),
            )

        eid, t_start, t_end, ev_type, severity, raw_payload = row
        payload = {}
        if raw_payload:
            try:
                payload = json.loads(raw_payload) if isinstance(raw_payload, str) else raw_payload
            except Exception:
                payload = {"raw": raw_payload}

        t_event = t_start
        t_lookback_start = t_event - (seconds_before * 1000)
        t_snap_start = t_event - 60000

        start_iso = datetime.datetime.fromtimestamp(t_lookback_start / 1000.0, tz=datetime.timezone.utc).isoformat()
        end_iso = datetime.datetime.fromtimestamp(t_event / 1000.0, tz=datetime.timezone.utc).isoformat()

        # Discover candidate signals from event_snapshots or signals_1s
        cur.execute(
            "SELECT DISTINCT signal FROM event_snapshots WHERE event_id = ?",
            (eid,),
        )
        snap_signals = [r[0] for r in cur.fetchall()]

        cur.execute(
            "SELECT DISTINCT signal FROM signals_1s WHERE ts >= ? AND ts <= ?",
            (t_lookback_start, t_snap_start),
        )
        s1s_signals = [r[0] for r in cur.fetchall()]

        candidate_signals = sorted(list(set(snap_signals + s1s_signals)))
        if not candidate_signals:
            cur.execute(
                "SELECT DISTINCT signal FROM signals_1m WHERE ts >= ? AND ts <= ?",
                (t_lookback_start, t_event),
            )
            candidate_signals = [r[0] for r in cur.fetchall()]

        precursors: list[dict[str, Any]] = []
        evidence_refs: list[str] = [f"event:{eid}"]
        if snap_signals:
            evidence_refs.append(f"event_snapshots:{eid}")
        if s1s_signals:
            evidence_refs.append("signals_1s")

        for sig in candidate_signals:
            # Multi-tier fetch: [t_lookback_start, t_snap_start) from signals_1s (or 1m)
            cur.execute(
                "SELECT ts, avg FROM signals_1s WHERE signal = ? AND ts >= ? AND ts < ? ORDER BY ts ASC",
                (sig, t_lookback_start, t_snap_start),
            )
            r1 = cur.fetchall()
            if not r1:
                cur.execute(
                    "SELECT ts, avg FROM signals_1m WHERE signal = ? AND ts >= ? AND ts < ? ORDER BY ts ASC",
                    (sig, t_lookback_start, t_snap_start),
                )
                r1 = cur.fetchall()

            # [t_snap_start, t_event] from event_snapshots (or signals_1s)
            cur.execute(
                "SELECT ts, value FROM event_snapshots WHERE event_id = ? AND signal = ? AND ts >= ? AND ts <= ? ORDER BY ts ASC",
                (eid, sig, t_snap_start, t_event),
            )
            r2 = cur.fetchall()
            if not r2:
                cur.execute(
                    "SELECT ts, avg FROM signals_1s WHERE signal = ? AND ts >= ? AND ts <= ? ORDER BY ts ASC",
                    (sig, t_snap_start, t_event),
                )
                r2 = cur.fetchall()

            pts = r1 + r2
            if len(pts) < 10:
                continue

            ts_list = [p[0] for p in pts]
            vals = [p[1] for p in pts]

            onset = detect_signal_deviation_onset(ts_list, vals)
            if onset:
                sec_before = round((t_event - onset["onset_ts"]) / 1000.0, 1)
                precursors.append({
                    "signal": sig,
                    "onset_ts": onset["onset_ts"],
                    "seconds_before_event": sec_before,
                    "baseline_mean": onset["baseline_mean"],
                    "final_val": onset["final_val"],
                    "delta": onset["delta"],
                    "pct_change": onset["pct_change"],
                })

        # Sort precursors chronologically (earliest onset first)
        precursors.sort(key=lambda x: x["onset_ts"])

        # Fetch clip refs if any
        cur.execute("SELECT id FROM clip_refs WHERE event_id = ?", (eid,))
        clips = [r[0] for r in cur.fetchall()]

        event_entry = {
            "event_id": eid,
            "type": ev_type,
            "ts_start": t_start,
            "ts_end": t_end,
            "severity": severity,
            "summary": f"{ev_type} (severity={severity})",
            "clip_refs": clips,
        }

        findings: list[dict[str, Any]] = []
        for idx, p in enumerate(precursors, start=1):
            sig = p["signal"]
            unit = get_signal_unit(sig)
            delta = p["delta"]
            direction = "dropped" if delta < 0 else "rose"
            sec = p["seconds_before_event"]
            findings.append({
                "id": f"f{idx}",
                "claim": (
                    f"{sig} deviation onset detected at {sec}s prior to {ev_type}: "
                    f"{direction} from baseline {p['baseline_mean']} to {p['final_val']} {unit} "
                    f"({delta:+.2f} {unit}, {p['pct_change']:+.1f}%)"
                ),
                "value": round(delta, 2),
                "unit": unit,
                "contribution_pct": None,
                "relation": "rule_backed_cause" if "pump" in sig or "temp" in sig else "observation",
                "confidence": 0.95,
                "timestamps": [p["onset_ts"]],
            })

        seq = [p["signal"] for p in precursors] + [ev_type]
        display = {
            "chart": "timeline",
            "series": [p["signal"] for p in precursors],
        }

        latency_ms = int((time.perf_counter() - t0) * 1000)
        return make_evidence_packet(
            tool="timeline_before",
            query_type="precursor_timeline",
            time_range=[start_iso, end_iso],
            findings=findings,
            events=[event_entry],
            evidence_refs=evidence_refs[:10],
            display=display,
            latency_ms=latency_ms,
        )
