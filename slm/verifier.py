"""Deterministic numeric, citation, and semantic verifier for VehicleGPT.

Enforces strict grounding against the EvidencePacket:
1. Every sentence must cite finding IDs [f1].
2. Numbers must match cited finding values/claims at displayed precision.
3. Causal wording ('caused by', 'due to') permitted ONLY for
   'attributed_contribution' or 'rule_backed_cause'.
4. Ungrounded hazard words ('danger', 'fire') not in packet are rejected.
5. Semantic reversals ('false alarm', 'safe to drive') are strictly rejected.
6. On any failure, automatically falls back to render_template_response(packet).
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any

from slm.templates import render_template_response

CAUSAL_TRIGGERS = [
    r"\bcaused\s+by\b",
    r"\bdue\s+to\b",
    r"\bbecause\s+of\b",
    r"\bled\s+to\b",
    r"\bresulted\s+in\b",
    r"\bresulting\s+in\b",
    r"\bresult\s+of\b",
]

HAZARD_WORDS = [
    r"\bdanger\b",
    r"\bdangerous\b",
    r"\bfire\b",
    r"\bexplosion\b",
    r"\bcatastrophic\b",
    r"\bhazardous\b",
    r"\bunsafe\b",
    r"\bcritical\s+failure\b",
    r"\bemergency\b",
]

SEMANTIC_REVERSALS = [
    r"\bfalse\s+alarm\b",
    r"\bsafe\s+to\s+drive\b",
    r"\bignore\s+(?:the\s+)?warning\b",
    r"\bignore\s+(?:the\s+)?alert\b",
    r"\bnothing\s+to\s+worry\s+about\b",
    r"\bharmless\b",
    r"\bno\s+risk\b",
    r"\bdisregard\b",
]

CITATION_REGEX = re.compile(r"\[(f\d+(?:,\s*f\d+)*)\]")
SENTENCE_SPLIT_REGEX = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\[])")
NUMBER_REGEX = re.compile(r"[-+]?\d+(?:\.\d+)?")


@dataclass
class VerificationResult:
    passed: bool
    text: str
    reason: str | None = None
    violation_type: str | None = None


def split_sentences(text: str) -> list[str]:
    """Split text into sentences while avoiding decimal splits."""
    text = text.strip()
    if not text:
        return []
    # Replace newlines with spaces first
    normalized = re.sub(r"\s+", " ", text)
    sentences = SENTENCE_SPLIT_REGEX.split(normalized)
    return [s.strip() for s in sentences if s.strip()]


def extract_numbers_from_text(text: str) -> list[float]:
    """Extract floating point numbers from text, ignoring finding IDs in brackets."""
    # Remove citations like [f1], [f1, f2] before extracting numbers
    cleaned = CITATION_REGEX.sub("", text)
    # Remove ISO dates like 2026-10-21 so year/month/day aren't parsed as arbitrary data floats
    cleaned = re.sub(r"\b\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}:\d{2}(?:Z)?)?\b", "", cleaned)
    tokens = NUMBER_REGEX.findall(cleaned)
    nums: list[float] = []
    for t in tokens:
        try:
            nums.append(float(t))
        except ValueError:
            pass
    return nums


def extract_all_packet_numbers(packet: dict[str, Any], finding_ids: list[str]) -> set[float]:
    """Collect all valid numbers associated with the cited findings and the packet."""
    valid_nums: set[float] = set()

    # Find the matching findings
    findings_map = {f.get("id"): f for f in packet.get("findings", [])}

    for fid in finding_ids:
        f = findings_map.get(fid)
        if not f:
            continue
        # value
        v = f.get("value")
        if v is not None:
            valid_nums.add(float(v))
        # contribution_pct
        cp = f.get("contribution_pct")
        if cp is not None:
            valid_nums.add(float(cp))
            valid_nums.add(float(-cp))
        # numbers in claim
        claim = f.get("claim", "")
        for n in NUMBER_REGEX.findall(claim):
            try:
                fn = float(n)
                valid_nums.add(fn)
                valid_nums.add(abs(fn))
            except ValueError:
                pass

    # Also add packet-level unexplained_pct if present
    up = packet.get("unexplained_pct")
    if up is not None:
        valid_nums.add(float(up))

    return valid_nums


def number_matches_any(num: float, valid_set: set[float], tol_pct: float = 0.02) -> bool:
    """Check if number matches any valid number within tolerance or rounding precision."""
    abs_num = abs(num)
    for v in valid_set:
        abs_v = abs(v)
        # Exact or close match
        if math.isclose(abs_num, abs_v, rel_tol=tol_pct, abs_tol=0.15):
            return True
        # Check integer rounding (e.g. 38% vs 38.4%)
        if round(abs_num) == round(abs_v):
            return True
    return False


def verify_response(text: str, packet: dict[str, Any]) -> VerificationResult:
    """Verify an SLM narration against the ground-truth EvidencePacket."""
    sentences = split_sentences(text)
    if not sentences:
        fallback = render_template_response(packet)
        return VerificationResult(
            passed=False,
            text=fallback,
            reason="Empty narration generated",
            violation_type="empty_response",
        )

    findings = packet.get("findings", [])
    findings_map = {f.get("id"): f for f in findings}

    # Packet text for hazard word check
    packet_text = (
        " ".join(f.get("claim", "") for f in findings)
        + " "
        + " ".join(e.get("summary", "") for e in packet.get("events", []))
    ).lower()

    for idx, sentence in enumerate(sentences):
        # 1. Semantic reversal check
        for pattern in SEMANTIC_REVERSALS:
            if re.search(pattern, sentence, re.IGNORECASE):
                fallback = render_template_response(packet)
                return VerificationResult(
                    passed=False,
                    text=fallback,
                    reason=f"Semantic reversal detected in sentence {idx+1}: '{sentence}' matches '{pattern}'",
                    violation_type="semantic_reversal",
                )

        # 2. Hazard / safety word check
        for pattern in HAZARD_WORDS:
            if re.search(pattern, sentence, re.IGNORECASE):
                # Only allowed if present in packet
                if not re.search(pattern, packet_text, re.IGNORECASE):
                    fallback = render_template_response(packet)
                    return VerificationResult(
                        passed=False,
                        text=fallback,
                        reason=f"Ungrounded hazard vocabulary in sentence {idx+1}: '{pattern}' not present in packet",
                        violation_type="ungrounded_safety_word",
                    )

        # 3. Citation check
        citation_matches = CITATION_REGEX.findall(sentence)
        if not citation_matches:
            fallback = render_template_response(packet)
            return VerificationResult(
                passed=False,
                text=fallback,
                reason=f"Sentence {idx+1} lacks finding citation: '{sentence}'",
                violation_type="missing_citation",
            )

        cited_ids: list[str] = []
        for match in citation_matches:
            parts = [p.strip() for p in match.split(",") if p.strip()]
            cited_ids.extend(parts)

        # Verify all cited IDs exist in packet
        for cid in cited_ids:
            if cid not in findings_map:
                fallback = render_template_response(packet)
                return VerificationResult(
                    passed=False,
                    text=fallback,
                    reason=f"Sentence {idx+1} cites nonexistent finding '{cid}'",
                    violation_type="invalid_finding_id",
                )

        # 4. Causal wording check
        has_causal_word = any(re.search(pat, sentence, re.IGNORECASE) for pat in CAUSAL_TRIGGERS)
        if has_causal_word:
            # Check if any cited finding allows causal wording
            has_causal_relation = any(
                findings_map[cid].get("relation") in ("attributed_contribution", "rule_backed_cause")
                for cid in cited_ids
            )
            if not has_causal_relation:
                fallback = render_template_response(packet)
                return VerificationResult(
                    passed=False,
                    text=fallback,
                    reason=f"Sentence {idx+1} uses causal wording without attributed_contribution/rule_backed_cause",
                    violation_type="unauthorized_causal_wording",
                )

        # 5. Number grounding check
        sentence_numbers = extract_numbers_from_text(sentence)
        valid_numbers = extract_all_packet_numbers(packet, cited_ids)

        for num in sentence_numbers:
            # Skip common non-data integers like 1st, 2nd, small ordinals or count 0
            if not number_matches_any(num, valid_numbers):
                fallback = render_template_response(packet)
                return VerificationResult(
                    passed=False,
                    text=fallback,
                    reason=f"Sentence {idx+1} contains ungrounded number {num} not matching cited findings {cited_ids}",
                    violation_type="ungrounded_number",
                )

    # All sentences passed verification!
    return VerificationResult(
        passed=True,
        text=text,
        reason=None,
        violation_type=None,
    )
