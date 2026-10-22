"""Implementation of lookup_dtc tool."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from store.ro_db import get_readonly_connection
from tools.base import make_evidence_packet
from tools.registry import register_tool


@register_tool("lookup_dtc")
def handle_lookup_dtc(args: dict[str, Any], db_path: Path | str) -> dict[str, Any]:
    """Look up diagnostic trouble code description, severity, and occurrence history.

    Args:
        args: {'code': 'P0A7E'}
        db_path: Path to vehicle database.
    """
    t0 = time.perf_counter()
    code = args["code"].strip().upper()

    conn = get_readonly_connection(db_path)
    cur = conn.cursor()

    # Knowledge lookup
    k_row = cur.execute(
        "SELECT code, description, related_causes FROM dtc_knowledge WHERE code = ?",
        (code,),
    ).fetchone()

    # Occurrence history lookup
    hist_rows = cur.execute(
        "SELECT id, ts, ecu, status, description FROM dtcs WHERE code = ? ORDER BY ts ASC",
        (code,),
    ).fetchall()
    conn.close()

    latency_ms = int((time.perf_counter() - t0) * 1000)

    if not k_row and not hist_rows:
        return make_evidence_packet(
            tool="lookup_dtc",
            query_type="dtc_lookup",
            time_range=["2026-10-01", "2026-10-28"],
            findings=[],
            evidence_refs=[],
            data_gaps=[{
                "reason": "signal_unknown",
                "detail": f"DTC '{code}' not found in knowledge base or diagnostic history",
            }],
            latency_ms=latency_ms,
        )

    findings: list[dict[str, Any]] = []
    evidence_refs: list[str] = []
    timestamps: list[int] = [r["ts"] for r in hist_rows]

    desc = k_row["description"] if k_row else (hist_rows[0]["description"] if hist_rows else "Unknown fault")
    ecu = hist_rows[0]["ecu"] if hist_rows else "ECU"

    f1_claim = f"DTC {code} ({ecu}): {desc}."
    if k_row and k_row["related_causes"]:
        f1_claim += f" Potential causes: {k_row['related_causes']}."

    findings.append({
        "id": "f1",
        "claim": f1_claim,
        "value": float(len(hist_rows)),
        "unit": "occurrences",
        "contribution_pct": None,
        "relation": "rule_backed_cause",
        "confidence": 1.0,
        "timestamps": timestamps,
    })

    if hist_rows:
        evidence_refs.extend(f"dtc:{r['id']}" for r in hist_rows)
        latest_ts = hist_rows[-1]["ts"]
        findings.append({
            "id": "f2",
            "claim": f"DTC {code} occurred {len(hist_rows)} time(s) in vehicle log, latest at epoch ms {latest_ts}",
            "value": float(len(hist_rows)),
            "unit": "count",
            "contribution_pct": None,
            "relation": "observation",
            "confidence": 1.0,
            "timestamps": timestamps,
        })

    return make_evidence_packet(
        tool="lookup_dtc",
        query_type="dtc_lookup",
        time_range=["2026-10-01", "2026-10-28"],
        findings=findings,
        evidence_refs=evidence_refs,
        latency_ms=latency_ms,
    )
