"""Test: derived metrics (range_per_charge S1 degradation)."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from sim.config import SimConfig
from sim.generator import generate_history


@pytest.fixture(scope="module")
def sim_db_derived(tmp_path_factory: pytest.TempPathFactory) -> Path:
    tmp = tmp_path_factory.mktemp("derived")
    db_path = tmp / "test.db"
    cfg = SimConfig(seed=42, days=28, out_db=db_path,
                    ground_truth_path=tmp / "gt.json")
    generate_history(days=28, seed=42, out_db=db_path, cfg=cfg)
    return db_path


@pytest.mark.slow
@pytest.mark.integration
class TestDerivedMetrics:
    def test_s1_range_drop_within_documented_tolerance(self, sim_db_derived: Path) -> None:
        """Verify S1 range reduction is within the documented ~10-15% tolerance."""
        conn = sqlite3.connect(str(sim_db_derived))
        rows = conn.execute(
            "SELECT day, value FROM digest_daily WHERE metric = 'range_per_charge' ORDER BY day"
        ).fetchall()
        conn.close()

        assert len(rows) >= 28

        # Weekday commute baseline (average of days 1-5)
        base_days = rows[0:5]
        base_rpc = sum(r[1] for r in base_days) / len(base_days)

        # Days 10-15 (S1 cooled state before S2 OTA update)
        s1_days = rows[9:15]
        s1_rpc = sum(r[1] for r in s1_days) / len(s1_days)

        drop_pct = (base_rpc - s1_rpc) / base_rpc * 100.0
        # Documented range drop: ~10-15%
        assert 10.0 <= drop_pct <= 15.0, (
            f"Expected S1 range drop ~10-15%, got {drop_pct:.1f}% "
            f"(base={base_rpc:.1f} km, s1={s1_rpc:.1f} km)"
        )

    def test_combined_s1_s2_drop_greater_than_s1_alone(self, sim_db_derived: Path) -> None:
        """Combined S1 + S2 degradation (day 28) should be larger than S1 alone."""
        conn = sqlite3.connect(str(sim_db_derived))
        rows = conn.execute(
            "SELECT day, value FROM digest_daily WHERE metric = 'range_per_charge' ORDER BY day"
        ).fetchall()
        conn.close()

        base_rpc = sum(r[1] for r in rows[0:5]) / 5.0
        late_s1_s2 = sum(r[1] for r in rows[23:28]) / 5.0

        combined_drop = (base_rpc - late_s1_s2) / base_rpc * 100.0
        assert combined_drop > 20.0, (
            f"Expected combined S1+S2 drop > 20%, got {combined_drop:.1f}%"
        )
