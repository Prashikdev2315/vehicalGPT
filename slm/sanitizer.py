"""Sanitizer for untrusted log messages and telemetry inputs.

Enforces:
1. Strict character length capping (<= 256 chars per log entry).
2. XML/HTML escaping (<, >, &, ", ') to neutralize prompt delimiters.
3. Explicit quarantine tagging (<untrusted_telemetry_snippet>...</untrusted_telemetry_snippet>).
4. Prevention of prompt injection into EvidencePackets and follow-up contexts.
"""
from __future__ import annotations

import html
import re

MAX_LOG_MESSAGE_CHARS = 256
MAX_USER_QUERY_CHARS = 512


def sanitize_log_message(
    msg: str,
    max_chars: int = MAX_LOG_MESSAGE_CHARS,
    wrap_snippet: bool = True,
) -> str:
    """Sanitize, escape, and length-cap untrusted vehicle log text.

    Args:
        msg: Raw untrusted log message from vehicle database or CAN logs.
        max_chars: Maximum allowable character length (default 256).
        wrap_snippet: Whether to tag as untrusted telemetry snippet.
    """
    if not msg:
        return ""

    # 1. Remove non-printable control characters (except space, tab, newline)
    cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", msg)

    # 2. Length-cap
    if len(cleaned) > max_chars:
        cleaned = cleaned[: max_chars - 3].rstrip() + "..."

    # 3. Escape XML/HTML delimiters
    escaped = html.escape(cleaned, quote=True)

    # 4. Quarantine wrapping
    if wrap_snippet:
        return f"<untrusted_telemetry_snippet>{escaped}</untrusted_telemetry_snippet>"
    return escaped


DELIMITER_PATTERNS = [
    r"<\|im_start\|>.*?(?:<\|im_end\|>|$)",
    r"<\|im_start\|>",
    r"<\|im_end\|>",
    r"<\|endoftext\|>",
    r"\[INST\].*?(?:\[/INST\]|$)",
    r"\[INST\]",
    r"\[/INST\]",
]


def sanitize_user_query(query: str, max_chars: int = MAX_USER_QUERY_CHARS) -> str:
    """Cap and sanitize user driver queries before router ingestion."""
    if not query:
        return ""
    # Strip null bytes and control chars
    cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", query)
    # Strip chat template delimiters and embedded assistant spoofing
    for p in DELIMITER_PATTERNS:
        cleaned = re.sub(p, "", cleaned, flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if len(cleaned) > max_chars:
        cleaned = cleaned[:max_chars].strip()
    return cleaned
