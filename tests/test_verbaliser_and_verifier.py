"""Tests for template engine, verbaliser prompts, and deterministic verifier."""
from __future__ import annotations

import pytest

from slm.templates import render_template_response
from slm.verbaliser import build_verbaliser_prompt, format_evidence_for_verbaliser
from slm.verifier import verify_response


@pytest.fixture
def sample_state_packet():
    return {
        "packet_id": "ev_0123456789ab",
        "tool": "current_state",
        "query_type": "current_state",
        "time_range": ["2026-10-21T00:00:00Z", "2026-10-21T18:00:00Z"],
        "findings": [
            {
                "id": "f1",
                "claim": "Current state of charge is 82.5%",
                "value": 82.5,
                "unit": "%",
                "relation": "observation",
                "confidence": 1.0,
            }
        ],
        "evidence_refs": ["signal:soc"],
        "data_gaps": [],
        "latency_ms": 2,
    }


@pytest.fixture
def sample_attribution_packet():
    return {
        "packet_id": "ev_abcdef123456",
        "tool": "explain_change",
        "query_type": "explain_change",
        "time_range": ["2026-10-01T00:00:00Z", "2026-10-21T18:00:00Z"],
        "findings": [
            {
                "id": "f1",
                "claim": "Ambient temperature drop",
                "value": None,
                "unit": None,
                "contribution_pct": 14.5,
                "relation": "attributed_contribution",
                "confidence": 0.95,
            },
            {
                "id": "f2",
                "claim": "HVAC heating usage increase",
                "value": None,
                "unit": None,
                "contribution_pct": 12.0,
                "relation": "attributed_contribution",
                "confidence": 0.92,
            },
            {
                "id": "f3",
                "claim": "Tire pressure decrease",
                "value": None,
                "unit": None,
                "contribution_pct": 3.2,
                "relation": "correlation",
                "confidence": 0.60,
            },
        ],
        "unexplained_pct": 12.0,
        "evidence_refs": ["signal:ambient_temp", "signal:hvac_power"],
        "data_gaps": [],
        "latency_ms": 5,
    }


def test_template_engine_instant_render(sample_state_packet):
    rendered = render_template_response(sample_state_packet)
    assert "[f1]" in rendered
    assert "82.5%" in rendered


def test_template_engine_attribution(sample_attribution_packet):
    rendered = render_template_response(sample_attribution_packet)
    assert "[f1]" in rendered
    assert "[f2]" in rendered
    assert "14.5%" in rendered
    assert "12.0%" in rendered
    assert "Unexplained variance is 12.0%" in rendered


def test_template_engine_data_gap():
    gap_packet = {
        "packet_id": "ev_000000000000",
        "tool": "get_events",
        "query_type": "get_events",
        "time_range": ["2026-09-01T00:00:00Z", "2026-09-05T00:00:00Z"],
        "findings": [],
        "evidence_refs": [],
        "data_gaps": [
            {
                "reason": "outside_retention",
                "detail": "Data before retention window pruned",
                "available_from": "2026-10-07T00:00:00Z",
            }
        ],
        "latency_ms": 1,
    }
    rendered = render_template_response(gap_packet)
    assert "outside retention" in rendered
    assert "2026-10-07T00:00:00Z" in rendered


def test_verifier_valid_narration(sample_state_packet):
    text = "The current state of charge is 82.5% [f1]."
    res = verify_response(text, sample_state_packet)
    assert res.passed is True
    assert res.text == text


def test_verifier_missing_citation(sample_state_packet):
    text = "The battery level is at 82.5%."
    res = verify_response(text, sample_state_packet)
    assert res.passed is False
    assert res.violation_type == "missing_citation"
    # Fallback applied
    assert "[f1]" in res.text


def test_verifier_invalid_citation(sample_state_packet):
    text = "The current battery state of charge is 82.5% [f99]."
    res = verify_response(text, sample_state_packet)
    assert res.passed is False
    assert res.violation_type == "invalid_finding_id"


def test_verifier_hallucinated_number(sample_state_packet):
    text = "The battery level is 99.4% [f1]."
    res = verify_response(text, sample_state_packet)
    assert res.passed is False
    assert res.violation_type == "ungrounded_number"


def test_verifier_causal_wording_allowed_for_attribution(sample_attribution_packet):
    text = "The range drop was caused by ambient temperature drop contributing 14.5% [f1]."
    res = verify_response(text, sample_attribution_packet)
    assert res.passed is True


def test_verifier_causal_wording_rejected_for_correlation(sample_attribution_packet):
    # f3 is only correlation
    text = "The range decrease was caused by tire pressure decrease [f3]."
    res = verify_response(text, sample_attribution_packet)
    assert res.passed is False
    assert res.violation_type == "unauthorized_causal_wording"


def test_verifier_ungrounded_hazard_word(sample_state_packet):
    text = "Current battery charge is 82.5% but there is a dangerous fire risk [f1]."
    res = verify_response(text, sample_state_packet)
    assert res.passed is False
    assert res.violation_type == "ungrounded_safety_word"


def test_verifier_semantic_reversal_rejected(sample_state_packet):
    text = "Current charge is 82.5% and the warning is a false alarm so it is safe to drive [f1]."
    res = verify_response(text, sample_state_packet)
    assert res.passed is False
    assert res.violation_type == "semantic_reversal"
