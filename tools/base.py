"""Base classes, evidence packet builder, and schema validator for tools."""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

import jsonschema

SCHEMA_PATH = Path("docs/evidence_packet.schema.json")
_EVIDENCE_SCHEMA: dict[str, Any] | None = None


def get_evidence_schema() -> dict[str, Any]:
    global _EVIDENCE_SCHEMA
    if _EVIDENCE_SCHEMA is None:
        with open(SCHEMA_PATH, encoding="utf-8") as f:
            _EVIDENCE_SCHEMA = json.load(f)
    return _EVIDENCE_SCHEMA


def validate_evidence_packet(packet: dict[str, Any]) -> None:
    """Validate an evidence packet against docs/evidence_packet.schema.json."""
    schema = get_evidence_schema()
    jsonschema.validate(instance=packet, schema=schema)


def make_evidence_packet(
    tool: str,
    query_type: str,
    time_range: list[str] | tuple[str, str],
    findings: list[dict[str, Any]] | None = None,
    events: list[dict[str, Any]] | None = None,
    unexplained_pct: float | None = None,
    evidence_refs: list[str] | None = None,
    data_gaps: list[dict[str, Any]] | None = None,
    display: dict[str, Any] | None = None,
    latency_ms: int = 0,
) -> dict[str, Any]:
    """Construct a schema-compliant evidence packet."""
    pid = f"ev_{uuid.uuid4().hex[:12]}"
    packet: dict[str, Any] = {
        "packet_id": pid,
        "tool": tool,
        "query_type": query_type,
        "time_range": list(time_range),
        "findings": findings or [],
        "evidence_refs": evidence_refs or [],
        "data_gaps": data_gaps or [],
        "latency_ms": max(0, int(latency_ms)),
    }
    if events is not None:
        packet["events"] = events
    if unexplained_pct is not None:
        packet["unexplained_pct"] = round(float(unexplained_pct), 1)
    if display is not None:
        packet["display"] = display

    # Ensure schema validity
    validate_evidence_packet(packet)
    return packet


def make_error_packet(
    tool: str,
    query_type: str,
    time_range: list[str] | tuple[str, str],
    reason: str,
    detail: str,
    available_from: str | None = None,
    latency_ms: int = 0,
) -> dict[str, Any]:
    """Helper to construct an evidence packet representing a data gap or validation failure."""
    gap: dict[str, Any] = {"reason": reason, "detail": detail}
    if available_from is not None:
        gap["available_from"] = available_from

    return make_evidence_packet(
        tool=tool,
        query_type=query_type,
        time_range=time_range,
        findings=[],
        evidence_refs=[],
        data_gaps=[gap],
        latency_ms=latency_ms,
    )
