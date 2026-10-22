"""Test: candump roundtrip — replay yields exact same values as direct load (D7)."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from ingest.can_adapter import CandumpReplayAdapter
from sim.config import SimConfig
from sim.generator import generate_history, write_candump


@pytest.fixture(scope="module")
def candump_data(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path, Path]:
    """Generate a short sim and a candump file, return (db, candump, dbc)."""
    tmp = tmp_path_factory.mktemp("candump")
    db_path = tmp / "test.db"
    cfg = SimConfig(seed=42, days=2, out_db=db_path,
                    ground_truth_path=tmp / "gt.json")
    generate_history(days=2, seed=42, out_db=db_path, cfg=cfg)

    # Write candump for a 10-minute window
    from datetime import datetime, timezone
    base_epoch = int(datetime(2026, 10, 1, tzinfo=timezone.utc).timestamp() * 1000)
    # Day 1, 8:00 AM, 10 minutes
    start = base_epoch + int(1 * 24 * 3600 * 1000) + int(8 * 3600 * 1000)
    candump_path = tmp / "test.log"
    write_candump(db_path, candump_path, start, 10 * 60 * 1000,
                  Path("docs/signals.dbc"))

    return db_path, candump_path, Path("docs/signals.dbc")


class TestCandumpRoundtrip:
    def test_candump_file_created(self, candump_data: tuple[Path, Path, Path]) -> None:
        _, candump_path, _ = candump_data
        assert candump_path.exists()
        assert candump_path.stat().st_size > 0

    def test_replay_values_exact_match(self, candump_data: tuple[Path, Path, Path]) -> None:
        """Replay candump and compare with DB values — must be EXACT (D7)."""
        db_path, candump_path, dbc_path = candump_data

        # Get original DB values for the window
        conn = sqlite3.connect(str(db_path))
        from datetime import datetime, timezone
        base_epoch = int(datetime(2026, 10, 1, tzinfo=timezone.utc).timestamp() * 1000)
        start = base_epoch + int(1 * 24 * 3600 * 1000) + int(8 * 3600 * 1000)
        end = start + 10 * 60 * 1000

        db_values: dict[tuple[int, str], float] = {}
        for row in conn.execute(
            "SELECT ts, signal, value FROM signals WHERE ts >= ? AND ts < ?",
            (start, end),
        ):
            db_values[(row[0], row[1])] = row[2]
        conn.close()

        if not db_values:
            pytest.skip("No signal data in the test window")

        # Replay candump
        adapter = CandumpReplayAdapter(candump_path, dbc_path)
        adapter.start()
        replay_values: dict[tuple[int, str], float] = {}
        for row in adapter.read():
            replay_values[(row.ts, row.signal)] = row.value
        adapter.stop()

        assert len(replay_values) > 0, "No data replayed from candump"

        # Check exact match for signals that appear in both
        matched = 0
        for key, replay_val in replay_values.items():
            if key in db_values:
                assert replay_val == db_values[key], (
                    f"Signal {key[1]} at ts={key[0]}: "
                    f"replay={replay_val} != db={db_values[key]} "
                    "(D7: values should be quantised to DBC resolution)"
                )
                matched += 1

        assert matched > 0, "No matching signals found between replay and DB"
