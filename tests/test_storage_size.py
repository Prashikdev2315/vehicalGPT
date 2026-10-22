"""Test: storage size per day vs PRD estimate."""
from __future__ import annotations

from pathlib import Path
import pytest

from sim.config import SimConfig
from sim.generator import generate_history, get_db_size_bytes


class TestStorageSize:
    def test_storage_mb_per_day_within_budget(self, tmp_path: Path) -> None:
        """Verify storage MB/day is reported and bounded well within the PRD ~70 MB/day estimate."""
        db_path = tmp_path / "test_size.db"
        cfg = SimConfig(seed=42, days=7, out_db=db_path,
                        ground_truth_path=tmp_path / "gt.json")
        summary = generate_history(days=7, seed=42, out_db=db_path, cfg=cfg)

        mb_per_day = summary["mb_per_day"]
        db_size_mb = summary["db_size_mb"]

        print(f"\nStorage Report: {db_size_mb:.2f} MB total across 7 days ({mb_per_day:.2f} MB/day)")
        # PRD specifies ~70 MB/day for 200 signals at 1 Hz; here ~40 signals should be ~15-30 MB/day
        assert mb_per_day > 0, "Database size must be positive"
        assert mb_per_day < 70.0, f"Storage per day ({mb_per_day:.2f} MB/day) exceeds PRD budget (70 MB/day)"
