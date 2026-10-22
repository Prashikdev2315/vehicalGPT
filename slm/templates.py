"""Deterministic template engine for immediate (<5 ms) driver-facing responses.

Generates structured, verified text directly from an EvidencePacket.
Every sentence includes finding citations [f1], [f2] so template responses
naturally satisfy the verifier contract.
"""
from __future__ import annotations

from typing import Any


def render_template_response(packet: dict[str, Any]) -> str:
    """Render a deterministic, citation-bearing response from an EvidencePacket in < 1 ms."""
    data_gaps = packet.get("data_gaps", [])
    findings = packet.get("findings", [])
    tool = packet.get("tool", "")

    # 1. Handle data gaps / empty data
    if data_gaps:
        gap = data_gaps[0]
        reason = gap.get("reason", "unknown")
        detail = gap.get("detail", "")
        avail = gap.get("available_from")
        if reason == "outside_retention" and avail:
            return f"Requested data is outside retention. Detailed records are available from {avail}."
        if reason == "no_events_found":
            return f"No events were found matching the requested criteria."
        if detail:
            return f"Data unavailable ({reason}): {detail}."
        return f"Data unavailable: {reason}."

    if not findings:
        return "No findings available for the specified query."

    # 2. Handle respond_direct (e.g. clarifications, safety refusals, out-of-scope)
    if tool == "respond_direct":
        sentences: list[str] = []
        for f in findings:
            fid = f.get("id", "f1")
            claim = f.get("claim", "").rstrip(".")
            if claim:
                sentences.append(f"{claim} [{fid}].")
        return " ".join(sentences) if sentences else "Request processed."

    # 3. Handle explain_change (attribution breakdown)
    if tool == "explain_change":
        sentences = []
        contrib_clauses = []
        for f in findings:
            fid = f.get("id", "f1")
            claim = f.get("claim", "")
            val = f.get("contribution_pct")
            rel = f.get("relation", "observation")
            if val is not None:
                contrib_clauses.append(f"{claim} ({val:.1f}%) [{fid}]")
            else:
                contrib_clauses.append(f"{claim} [{fid}]")

        if contrib_clauses:
            sentences.append("Identified contributors: " + "; ".join(contrib_clauses) + ".")

        unexplained = packet.get("unexplained_pct")
        if unexplained is not None and unexplained > 0:
            sentences.append(f"Unexplained variance is {unexplained:.1f}%.")

        return " ".join(sentences)

    # 4. Handle get_events and timeline_before
    if tool in ("get_events", "timeline_before"):
        sentences = []
        for f in findings:
            fid = f.get("id", "f1")
            claim = f.get("claim", "").rstrip(".")
            sentences.append(f"{claim} [{fid}].")
        return " ".join(sentences)

    # 5. Handle current_state, trend, compare, largest_change, lookup_dtc, search_logs
    sentences = []
    for f in findings:
        fid = f.get("id", "f1")
        claim = f.get("claim", "").rstrip(".")
        if claim:
            sentences.append(f"{claim} [{fid}].")

    return " ".join(sentences)
