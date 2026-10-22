"""Tests for explain_change tool and attribution engine."""
from __future__ import annotations

import json
from pathlib import Path
import pytest

import tools
from insight.attribution import decompose_metric_change
from tools.base import validate_evidence_packet
from tools.registry import dispatch_tool


def test_explain_change_s1_s2_overlap():
    """Verify attribution breakdown on real data for S1/S2 overlap window vs baseline."""
    # Days 1-5 (2026-10-01 to 2026-10-05) vs Days 24-28 (2026-10-24 to 2026-10-28)
    result = dispatch_tool(
        "explain_change",
        {
            "metric": "range_per_charge",
            "window_a": "2026-10-01/2026-10-05",
            "window_b": "2026-10-24/2026-10-28",
        },
        db_path="data/vehicle.db",
    )
    validate_evidence_packet(result)

    assert result["tool"] == "explain_change"
    assert result["query_type"] == "attribution_decomposition"

    findings = result["findings"]
    assert len(findings) >= 2, f"Expected observation + causes, got {findings}"

    # Verify net drop finding
    net_f = findings[0]
    assert net_f["relation"] == "observation"
    assert net_f["value"] < 0, f"Range should drop, got {net_f['value']}"

    # Extract cause findings
    hvac_f = next((f for f in findings if "hvac" in f["claim"].lower() or "cooling" in f["claim"].lower()), None)
    ota_f = next((f for f in findings if "ota" in f["claim"].lower() or "firmware" in f["claim"].lower()), None)

    assert hvac_f is not None, "Expected HVAC / temperature cause finding"
    assert hvac_f["contribution_pct"] is not None
    # Compare with ground truth in ground_truth.json (51.4%): must be within +/- 10 pp
    with open("eval/ground_truth.json", encoding="utf-8") as f:
        gt = json.load(f)
    gt_s1_s2 = next(e for e in gt if e["id"] == "S1_S2_overlap")
    gt_hvac = gt_s1_s2.get("extra", {}).get("hvac_share_pct", 51.4)

    assert abs(hvac_f["contribution_pct"] - gt_hvac) <= 10.0, (
        f"HVAC contribution {hvac_f['contribution_pct']}% not within 10 pp of ground truth {gt_hvac}%"
    )

    # Check relation gating: high quality fit must be attributed_contribution
    assert hvac_f["relation"] == "attributed_contribution"

    if ota_f is not None:
        gt_ota = gt_s1_s2.get("extra", {}).get("ota_share_pct", 12.4)
        # OTA contribution should be present and reasonable
        assert ota_f["contribution_pct"] is not None
        assert ota_f["relation"] in ("attributed_contribution", "correlation")


def test_explain_change_energy_per_km():
    """Verify attribution on energy_per_km."""
    result = dispatch_tool(
        "explain_change",
        {
            "metric": "energy_per_km",
            "window_a": "2026-10-01/2026-10-05",
            "window_b": "2026-10-24/2026-10-28",
        },
        db_path="data/vehicle.db",
    )
    validate_evidence_packet(result)
    assert result["findings"][0]["value"] > 0, "EPK should increase from A to B"


def test_explain_change_unknown_metric():
    """Verify unknown metric returns error packet."""
    result = dispatch_tool(
        "explain_change",
        {
            "metric": "quantum_flux_density",
            "window_a": "2026-10-01/2026-10-05",
            "window_b": "2026-10-24/2026-10-28",
        },
        db_path="data/vehicle.db",
    )
    assert len(result["data_gaps"]) > 0
    assert result["data_gaps"][0]["reason"] == "signal_unknown"


def test_attribution_counterfactual_validation(tmp_path):
    """Counterfactual validation: verify attribution engine accuracy against known synthetic changes."""
    # Pure test of decompose_metric_change without importing SimConfig
    import sqlite3
    db_file = tmp_path / "counterfactual.db"
    con = sqlite3.connect(db_file)
    cur = con.cursor()
    # Create minimal schema for trips & events
    cur.execute("""
        CREATE TABLE trips (
            id INTEGER PRIMARY KEY,
            ts_start INTEGER,
            ts_end INTEGER,
            distance_km REAL,
            energy_kwh REAL,
            fuel_l REAL,
            avg_speed_kph REAL,
            city_share REAL,
            highway_share REAL,
            avg_ambient_c REAL,
            hvac_energy_kwh REAL
        )
    """)
    cur.execute("""
        CREATE TABLE events (
            id INTEGER PRIMARY KEY,
            ts_start INTEGER,
            ts_end INTEGER,
            type TEXT,
            source TEXT,
            severity TEXT,
            payload TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE digest_daily (
            day TEXT,
            metric TEXT,
            value REAL,
            n_trips INTEGER,
            PRIMARY KEY(day, metric)
        )
    """)

    # Window A (baseline): 100 km, 10 kWh total (100 Wh/km), 1 kWh HVAC (10 Wh/km), prop 90 Wh/km
    t_a1 = 1000000
    t_a2 = 2000000
    cur.execute("INSERT INTO trips VALUES (1, ?, ?, 100.0, 10.0, 0, 40.0, 0.5, 0.5, 25.0, 1.0)", (t_a1, t_a2))

    # Window B: 100 km, 14 kWh total (140 Wh/km), 3 kWh HVAC (30 Wh/km), prop 110 Wh/km
    # Total delta EPK = +40 Wh/km.
    # True HVAC delta = +20 Wh/km (50% of total delta).
    # True OTA delta = +20 Wh/km (50% of total delta).
    t_b1 = 8000000
    t_b2 = 9000000
    cur.execute("INSERT INTO trips VALUES (2, ?, ?, 100.0, 14.0, 0, 40.0, 0.5, 0.5, 10.0, 3.0)", (t_b1, t_b2))

    # Add OTA event at t = 5000000
    t_ota = 5000000
    cur.execute("INSERT INTO events VALUES (1, ?, ?, 'ota_update', 'system', 'info', '{}')", (t_ota, t_ota + 1000))
    # Before OTA trip (t=4500000): prop 90 Wh/km
    cur.execute("INSERT INTO trips VALUES (3, 4400000, 4600000, 100.0, 10.0, 0, 40.0, 0.5, 0.5, 20.0, 1.0)")
    # After OTA trip (t=5500000): prop 110 Wh/km (step = +20 Wh/km, +22.2%)
    cur.execute("INSERT INTO trips VALUES (4, 5400000, 5600000, 100.0, 12.0, 0, 40.0, 0.5, 0.5, 20.0, 1.0)")
    con.commit()
    con.close()

    res = decompose_metric_change("energy_per_km", (t_a1, t_a2), (t_b1, t_b2), db_path=db_file)
    assert res["delta"] == pytest.approx(40.0, abs=0.5)

    causes = {c["cause"]: c["contribution_pct"] for c in res["causes"]}
    # True HVAC contribution = 50%
    assert abs(causes["hvac_ambient_temperature"] - 50.0) <= 10.0
    # True OTA contribution = 50%
    assert abs(causes["ota_update_efficiency_step"] - 50.0) <= 10.0
    assert res["unexplained_pct"] <= 10.0
