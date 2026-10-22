"""Tests for timeline_before precursor deviation onset sequencing tool."""
from __future__ import annotations

import pytest
import tools
from tools.base import validate_evidence_packet
from tools.registry import dispatch_tool


def test_timeline_before_s3_battery_overtemp():
    """Verify coolant_pump_duty drops before pack_temp rises for S3 battery overheat."""
    result = dispatch_tool(
        "timeline_before",
        {
            "event_type": "battery_overtemp_warning",
            "occurrence": "latest",
            "seconds_before": 600,
        },
        db_path="data/vehicle.db",
    )
    # 1. Evidence packet schema validation
    validate_evidence_packet(result)

    assert result["tool"] == "timeline_before"
    assert result["query_type"] == "precursor_timeline"
    assert len(result["events"]) == 1
    assert result["events"][0]["type"] == "battery_overtemp_warning"

    findings = result["findings"]
    assert len(findings) >= 2, f"Expected at least pump and pack temp precursors, got {findings}"

    # Extract claims
    claims = [f["claim"] for f in findings]
    pump_findings = [f for f in findings if "coolant_pump_duty" in f["claim"]]
    temp_findings = [f for f in findings if "pack_temp" in f["claim"]]

    assert len(pump_findings) > 0, "Expected coolant_pump_duty finding"
    assert len(temp_findings) > 0, "Expected pack_temp finding"

    pump_f = pump_findings[0]
    temp_f = temp_findings[0]

    # Check sequencing: coolant_pump_duty onset timestamp must be strictly earlier than pack_temp onset
    assert pump_f["timestamps"][0] < temp_f["timestamps"][0], (
        f"Pump onset {pump_f['timestamps'][0]} must precede temp onset {temp_f['timestamps'][0]}"
    )

    # Check deltas: pump duty dropped (negative), pack temp rose (positive)
    assert pump_f["value"] < 0, f"Pump duty should drop, got {pump_f['value']}"
    assert temp_f["value"] > 0, f"Pack temp should rise, got {temp_f['value']}"

    # Verify chronological sequence in display series
    series = result["display"]["series"]
    assert series.index("coolant_pump_duty") < series.index("pack_temp")


def test_timeline_before_by_event_id():
    """Verify lookup by specific event ID."""
    result = dispatch_tool(
        "timeline_before",
        {
            "event_id": 17,
            "seconds_before": 600,
        },
        db_path="data/vehicle.db",
    )
    validate_evidence_packet(result)
    assert len(result["events"]) == 1
    assert result["events"][0]["event_id"] == 17
    assert len(result["findings"]) > 0


def test_timeline_before_missing_event():
    """Verify graceful handling when event does not exist."""
    result = dispatch_tool(
        "timeline_before",
        {
            "event_id": 999999,
            "seconds_before": 600,
        },
        db_path="data/vehicle.db",
    )
    validate_evidence_packet(result)
    assert len(result["events"]) == 0
    assert len(result["findings"]) == 0
    assert len(result["data_gaps"]) > 0


@pytest.mark.slow
@pytest.mark.integration
def test_timeline_precursors_multi_seed(tmp_path):
    """Verify coolant_pump_duty onset precedes pack_temp onset across 5 different seeds."""
    from sim.config import SimConfig
    from sim.generator import generate_history

    seeds = [42, 101, 202, 303, 404]
    results = []

    for seed in seeds:
        db_file = tmp_path / f"test_s3_seed_{seed}.db"
        gt_file = tmp_path / f"gt_seed_{seed}.json"
        cfg = SimConfig(seed=seed, days=1, s3_event_day=0, out_db=db_file, ground_truth_path=gt_file)
        generate_history(days=1, seed=seed, out_db=db_file, cfg=cfg)

        res = dispatch_tool(
            "timeline_before",
            {"event_type": "battery_overtemp_warning", "occurrence": "latest", "seconds_before": 600},
            db_path=db_file,
        )
        validate_evidence_packet(res)

        findings = res["findings"]
        pump_f = next((f for f in findings if "coolant_pump_duty" in f["claim"]), None)
        temp_f = next((f for f in findings if "pack_temp" in f["claim"]), None)

        assert pump_f is not None, f"Seed {seed}: coolant_pump_duty onset not detected"
        assert temp_f is not None, f"Seed {seed}: pack_temp onset not detected"

        pump_ts = pump_f["timestamps"][0]
        temp_ts = temp_f["timestamps"][0]
        ev_ts = res["events"][0]["ts_start"]

        assert pump_ts < temp_ts, f"Seed {seed}: Pump onset {pump_ts} must precede temp onset {temp_ts}"
        assert pump_ts < ev_ts
        assert temp_ts <= ev_ts

        results.append({
            "seed": seed,
            "pump_sec_before": (ev_ts - pump_ts) / 1000.0,
            "temp_sec_before": (ev_ts - temp_ts) / 1000.0,
            "lead_time_sec": (temp_ts - pump_ts) / 1000.0,
        })

    # Ensure all 5 seeds passed with pump leading pack_temp
    assert len(results) == 5
    for r in results:
        assert r["lead_time_sec"] > 0

