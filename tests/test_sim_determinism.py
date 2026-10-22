"""Test: simulator determinism — same seed produces identical output."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from sim.generator import generate_history
from sim.config import SimConfig


def _row_hash(db_path: Path) -> dict[str, list[tuple]]:
    """Extract all rows from key tables for comparison."""
    conn = sqlite3.connect(str(db_path))
    result = {}
    for table in ["signals", "trips", "events", "dtcs", "digest_daily",
                   "event_snapshots"]:
        try:
            rows = conn.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
            result[table] = rows
        except sqlite3.OperationalError:
            result[table] = []
    conn.close()
    return result


@pytest.mark.slow
@pytest.mark.timeout(120)
class TestSimDeterminism:
    def test_same_seed_identical_output(self, tmp_path: Path) -> None:
        """Two runs with the same seed must produce identical DB rows."""
        db1 = tmp_path / "run1.db"
        db2 = tmp_path / "run2.db"

        # Use a short simulation for speed
        cfg1 = SimConfig(seed=99, days=3, out_db=db1)
        cfg2 = SimConfig(seed=99, days=3, out_db=db2)

        generate_history(days=3, seed=99, out_db=db1, cfg=cfg1)
        generate_history(days=3, seed=99, out_db=db2, cfg=cfg2)

        rows1 = _row_hash(db1)
        rows2 = _row_hash(db2)

        for table in rows1:
            assert len(rows1[table]) == len(rows2[table]), (
                f"Table {table}: row count differs "
                f"({len(rows1[table])} vs {len(rows2[table])})"
            )
            for i, (r1, r2) in enumerate(zip(rows1[table], rows2[table])):
                assert r1 == r2, (
                    f"Table {table}, row {i}: values differ\n"
                    f"  run1: {r1}\n  run2: {r2}"
                )

    def test_different_seed_different_output(self, tmp_path: Path) -> None:
        """Different seeds must produce different data."""
        db1 = tmp_path / "seed1.db"
        db2 = tmp_path / "seed2.db"

        generate_history(days=2, seed=1, out_db=db1,
                        cfg=SimConfig(seed=1, days=2, out_db=db1))
        generate_history(days=2, seed=2, out_db=db2,
                        cfg=SimConfig(seed=2, days=2, out_db=db2))

        rows1 = _row_hash(db1)
        rows2 = _row_hash(db2)

        # Signals should differ
        assert rows1["signals"] != rows2["signals"]
