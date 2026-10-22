"""Test: every ground-truth event is present in the DB."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from sim.config import SimConfig
from sim.generator import generate_history


@pytest.fixture(scope="module")
def sim_db(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    """Generate a short simulation and return (db_path, gt_path)."""
    tmp = tmp_path_factory.mktemp("gt")
    db_path = tmp / "test.db"
    gt_path = tmp / "ground_truth.json"
    cfg = SimConfig(
        seed=42, days=28, out_db=db_path,
        ground_truth_path=gt_path,
    )
    generate_history(days=28, seed=42, out_db=db_path, cfg=cfg)
    return db_path, gt_path


@pytest.mark.slow
@pytest.mark.integration
class TestGroundTruth:
    def test_ground_truth_file_exists(self, sim_db: tuple[Path, Path]) -> None:
        _, gt_path = sim_db
        assert gt_path.exists()

    def test_ground_truth_valid_json(self, sim_db: tuple[Path, Path]) -> None:
        _, gt_path = sim_db
        with open(gt_path) as f:
            data = json.load(f)
        assert isinstance(data, list)
        assert len(data) >= 5  # S1-S5 at minimum

    def test_s1_range_reduction_present(self, sim_db: tuple[Path, Path]) -> None:
        _, gt_path = sim_db
        with open(gt_path) as f:
            data = json.load(f)
        s1 = next((e for e in data if e["id"] == "S1"), None)
        assert s1 is not None
        assert "range" in s1["scenario"].lower()
        assert "extra" in s1 and "measured_drop_pct" in s1["extra"]
        drop_pct = s1["extra"]["measured_drop_pct"]
        assert 10.0 <= drop_pct <= 15.0, (
            f"Expected S1 drop between 10-15%, got {drop_pct}%"
        )

    def test_s2_ota_event_in_db(self, sim_db: tuple[Path, Path]) -> None:
        db_path, _ = sim_db
        conn = sqlite3.connect(str(db_path))
        rows = conn.execute(
            "SELECT * FROM events WHERE type = 'ota_update'"
        ).fetchall()
        conn.close()
        assert len(rows) >= 1

    def test_s3_battery_overtemp_event_and_dtc(self, sim_db: tuple[Path, Path]) -> None:
        db_path, _ = sim_db
        conn = sqlite3.connect(str(db_path))

        events = conn.execute(
            "SELECT * FROM events WHERE type = 'battery_overtemp_warning'"
        ).fetchall()
        assert len(events) >= 1, "S3: battery_overtemp_warning event missing"

        dtcs = conn.execute(
            "SELECT * FROM dtcs WHERE code = 'P0A7E'"
        ).fetchall()
        assert len(dtcs) >= 1, "S3: DTC P0A7E missing"
        conn.close()

    def test_s4_adas_disengagements(self, sim_db: tuple[Path, Path]) -> None:
        db_path, _ = sim_db
        conn = sqlite3.connect(str(db_path))
        events = conn.execute(
            "SELECT * FROM events WHERE type = 'adas_disengagement'"
        ).fetchall()
        conn.close()
        assert len(events) >= 3, (
            f"S4: expected >= 3 ADAS disengagements, got {len(events)}"
        )

    def test_s1_s2_overlap_in_ground_truth(self, sim_db: tuple[Path, Path]) -> None:
        _, gt_path = sim_db
        with open(gt_path) as f:
            data = json.load(f)
        overlap = next((e for e in data if e["id"] == "S1_S2_overlap"), None)
        assert overlap is not None, "S1_S2_overlap missing from ground_truth"
        assert isinstance(overlap["cause"], list)
        assert len(overlap["cause"]) == 2

    def test_charging_sessions_exist(self, sim_db: tuple[Path, Path]) -> None:
        db_path, _ = sim_db
        conn = sqlite3.connect(str(db_path))
        events = conn.execute(
            "SELECT * FROM events WHERE type = 'charging_session'"
        ).fetchall()
        conn.close()
        assert len(events) >= 5, "Expected multiple charging sessions over 28 days"

    def test_digest_daily_has_range_per_charge(self, sim_db: tuple[Path, Path]) -> None:
        db_path, _ = sim_db
        conn = sqlite3.connect(str(db_path))
        rows = conn.execute(
            "SELECT * FROM digest_daily WHERE metric = 'range_per_charge'"
        ).fetchall()
        conn.close()
        assert len(rows) >= 20, "Expected range_per_charge digests for most days"

    def test_trips_have_no_fuel(self, sim_db: tuple[Path, Path]) -> None:
        """Pure EV: fuel_l must be NULL for all trips (D3)."""
        db_path, _ = sim_db
        conn = sqlite3.connect(str(db_path))
        rows = conn.execute(
            "SELECT fuel_l FROM trips WHERE fuel_l IS NOT NULL"
        ).fetchall()
        conn.close()
        assert len(rows) == 0, "Pure EV: no trips should have fuel_l"
