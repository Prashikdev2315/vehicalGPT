"""Grounded verbaliser prompt builder and streaming narrator for VehicleGPT.

Translates verified EvidencePackets into natural, driver-facing summaries
with strict citation requirements: every sentence must cite finding IDs [f1].
"""
from __future__ import annotations

import json
from typing import Any, Iterator

from slm.engine import SLMEngine

VERBALISER_SYSTEM_PROMPT = """You are VehicleGPT's verbaliser. Restate ONLY the factual findings from the evidence packet.
STRICT RULES:
1. Every sentence MUST end with its supporting finding citation in brackets, e.g. [f1] or [f1, f2].
2. State numbers and units EXACTLY as given in the findings. Never round differently or invent values.
3. Causal wording ('caused by', 'due to', 'led to', 'result of') is ONLY allowed if relation is 'attributed_contribution' or 'rule_backed_cause'. For 'correlation' or 'observation', use neutral phrases ('coincided with', 'associated with', 'observed').
4. Never use hazard or emergency words ('danger', 'fire', 'catastrophic', 'critical') unless explicitly in the findings.
5. Never use dismissive semantic reversals ('false alarm', 'safe to drive', 'ignore warning', 'harmless').
6. Do not include tool syntax, code, or speculative advice. Be concise and driver-friendly."""


def format_evidence_for_verbaliser(packet: dict[str, Any]) -> str:
    """Format an EvidencePacket into structured text for the verbaliser prompt."""
    lines: list[str] = [f"Tool: {packet.get('tool', 'unknown')}"]
    tr = packet.get("time_range")
    if tr and len(tr) == 2:
        lines.append(f"Time Range: {tr[0]} to {tr[1]}")

    findings = packet.get("findings", [])
    if findings:
        lines.append("Findings:")
        for f in findings:
            fid = f.get("id", "f1")
            claim = f.get("claim", "")
            relation = f.get("relation", "observation")
            val = f.get("value")
            unit = f.get("unit")
            contrib = f.get("contribution_pct")
            parts = [f"[{fid}] {claim}", f"(relation: {relation})"]
            if val is not None:
                parts.append(f"value: {val} {unit or ''}".strip())
            if contrib is not None:
                parts.append(f"contribution: {contrib}%")
            lines.append("  - " + " ".join(parts))

    unexplained = packet.get("unexplained_pct")
    if unexplained is not None:
        lines.append(f"Unexplained Variance: {unexplained}%")

    data_gaps = packet.get("data_gaps", [])
    if data_gaps:
        lines.append("Data Gaps:")
        for g in data_gaps:
            reason = g.get("reason", "unknown")
            detail = g.get("detail", "")
            avail = g.get("available_from")
            gap_str = f"  - Reason: {reason}"
            if detail:
                gap_str += f", Detail: {detail}"
            if avail:
                gap_str += f", Available from: {avail}"
            lines.append(gap_str)

    events = packet.get("events", [])
    if events:
        lines.append(f"Events Count: {len(events)}")
        for ev in events[:5]:  # limit to top 5 to respect token budget
            lines.append(f"  - Event {ev.get('event_id')}: {ev.get('type')} ({ev.get('severity')}) at {ev.get('ts_start')}")

    return "\n".join(lines)


def build_verbaliser_prompt(packet: dict[str, Any], user_query: str) -> list[dict[str, str]]:
    """Build chat messages for verbaliser generation."""
    evidence_text = format_evidence_for_verbaliser(packet)
    user_content = f"Driver Query: {user_query}\n\nEvidence Packet:\n{evidence_text}\n\nProvide the factual summary with citations."
    return [
        {"role": "system", "content": VERBALISER_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


def generate_narration(
    engine: SLMEngine,
    packet: dict[str, Any],
    user_query: str,
    max_tokens: int = 160,
    temperature: float = 0.1,
) -> str:
    """Generate non-streaming factual narration for an evidence packet."""
    messages = build_verbaliser_prompt(packet, user_query)
    # Verbalisation should be strictly deterministic
    result = engine.chat(
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
    )
    return result.strip()


def generate_narration_stream(
    engine: SLMEngine,
    packet: dict[str, Any],
    user_query: str,
    max_tokens: int = 160,
    temperature: float = 0.1,
) -> Iterator[str]:
    """Stream factual narration tokens for low-latency streaming."""
    messages = build_verbaliser_prompt(packet, user_query)
    for token in engine.chat_stream(
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
    ):
        yield token
