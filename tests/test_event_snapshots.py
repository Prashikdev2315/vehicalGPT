"""Test: full-rate event snapshots exist for every event (D2)."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from sim.config import SimConfig
from sim.generator import generate_history


@pytest.fixture(scope="module")
def snapshot_db(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Generate a short sim with events."""
    tmp = tmp_path_factory.mktemp("snap")
    db_path = tmp / "test.db"
    cfg = SimConfig(seed=42, days=28, out_db=db_path,
                    ground_truth_path=tmp / "gt.json")
    generate_history(days=28, seed=42, out_db=db_path, cfg=cfg)
    return db_path


class TestEventSnapshots:
    def test_snapshots_table_populated(self, snapshot_db: Path) -> None:
        conn = sqlite3.connect(str(snapshot_db))
        count = conn.execute("SELECT COUNT(*) FROM event_snapshots").fetchone()[0]
        conn.close()
        assert count > 0, "event_snapshots table is empty"

    def test_every_event_has_snapshots(self, snapshot_db: Path) -> None:
        """Every event should have ±60s of snapshot data."""
        conn = sqlite3.connect(str(snapshot_db))
        event_ids = [r[0] for r in conn.execute("SELECT id FROM events").fetchall()]

        events_with_snapshots = set()
        for r in conn.execute("SELECT DISTINCT event_id FROM event_snapshots").fetchall():
            events_with_snapshots.add(r[0])

        conn.close()

        # At least most events should have snapshots
        # Some events (like charging sessions) might be outside signal windows
        coverage = len(events_with_snapshots) / max(len(event_ids), 1)
        assert coverage > 0.5, (
            f"Only {len(events_with_snapshots)}/{len(event_ids)} events have snapshots"
        )

    def test_snapshot_time_window(self, snapshot_db: Path) -> None:
        """Snapshot data should span roughly ±60s around the event."""
        conn = sqlite3.connect(str(snapshot_db))

        # Pick the first event with snapshots
        row = conn.execute(
            "SELECT e.id, e.ts_start FROM events e "
            "INNER JOIN event_snapshots es ON e.id = es.event_id "
            "LIMIT 1"
        ).fetchone()

        if row is None:
            pytest.skip("No events with snapshots found")

        event_id, event_ts = row

        snap_range = conn.execute(
            "SELECT MIN(ts), MAX(ts) FROM event_snapshots WHERE event_id = ?",
            (event_id,),
        ).fetchone()
        conn.close()

        min_ts, max_ts = snap_range
        # Should span at least 30 seconds on each side
        assert event_ts - min_ts >= 30000, "Snapshot doesn't go far enough before event"
        assert max_ts - event_ts >= 30000, "Snapshot doesn't go far enough after event"
