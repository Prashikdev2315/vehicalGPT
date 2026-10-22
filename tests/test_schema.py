"""Test: schema matches docs/schema.sql exactly, including event_snapshots."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from store.db import init_db

SCHEMA_PATH = Path("docs/schema.sql")


@pytest.fixture
def db_conn(tmp_path: Path) -> sqlite3.Connection:
    """Create a fresh DB from the contract schema."""
    db_path = tmp_path / "test.db"
    return init_db(db_path, SCHEMA_PATH)


def _get_tables(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    return {r[0] for r in rows}


def _get_indices(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    return {r[0] for r in rows}


EXPECTED_TABLES = {
    "signal_catalog",
    "signals",
    "signals_1s",
    "signals_1m",
    "trips",
    "digest_daily",
    "events",
    "clip_refs",
    "dtcs",
    "dtc_knowledge",
    "log_templates",
    "logs",
    "logs_fts",
    "logs_fts_data",
    "logs_fts_idx",
    "logs_fts_docsize",
    "logs_fts_config",
    "insight_cache",
    "event_snapshots",
    "retention_policy",
}

EXPECTED_INDICES = {
    "idx_signals_sig_ts",
    "idx_trips_start",
    "idx_events_type_ts",
    "idx_dtcs_code_ts",
    "idx_logs_ts",
}


class TestSchema:
    def test_all_tables_exist(self, db_conn: sqlite3.Connection) -> None:
        tables = _get_tables(db_conn)
        for t in EXPECTED_TABLES:
            assert t in tables, f"Missing table: {t}"

    def test_no_extra_tables(self, db_conn: sqlite3.Connection) -> None:
        tables = _get_tables(db_conn)
        # Allow FTS shadow tables
        non_fts = {t for t in tables if not t.startswith("logs_fts_")}
        expected_non_fts = {t for t in EXPECTED_TABLES if not t.startswith("logs_fts_")}
        extra = non_fts - expected_non_fts
        assert not extra, f"Unexpected tables: {extra}"

    def test_all_indices_exist(self, db_conn: sqlite3.Connection) -> None:
        indices = _get_indices(db_conn)
        for idx in EXPECTED_INDICES:
            assert idx in indices, f"Missing index: {idx}"

    def test_event_snapshots_columns(self, db_conn: sqlite3.Connection) -> None:
        """Verify event_snapshots table has correct schema (contract)."""
        info = db_conn.execute("PRAGMA table_info(event_snapshots)").fetchall()
        cols = {row[1]: row[2] for row in info}
        assert "event_id" in cols
        assert "ts" in cols
        assert "signal" in cols
        assert "value" in cols
        assert cols["event_id"] == "INTEGER"
        assert cols["ts"] == "INTEGER"
        assert cols["signal"] == "TEXT"
        assert cols["value"] == "REAL"

    def test_event_snapshots_pk(self, db_conn: sqlite3.Connection) -> None:
        """event_snapshots PK is (event_id, signal, ts)."""
        # Insert and verify uniqueness constraint
        db_conn.execute(
            "INSERT INTO events (ts_start, type, source) VALUES (1000, 'test', 'test')"
        )
        eid = db_conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        db_conn.execute(
            "INSERT INTO event_snapshots (event_id, ts, signal, value) VALUES (?, 100, 'soc', 50.0)",
            (eid,),
        )
        # Duplicate should fail
        with pytest.raises(sqlite3.IntegrityError):
            db_conn.execute(
                "INSERT INTO event_snapshots (event_id, ts, signal, value) VALUES (?, 100, 'soc', 60.0)",
                (eid,),
            )

    def test_event_snapshots_retention_policy(self, db_conn: sqlite3.Connection) -> None:
        """event_snapshots has a retention_policy row with NULL keep_days."""
        row = db_conn.execute(
            "SELECT keep_days FROM retention_policy WHERE table_name='event_snapshots'"
        ).fetchone()
        assert row is not None, "Missing retention_policy for event_snapshots"
        assert row[0] is None, "event_snapshots should have NULL keep_days (permanent)"

    def test_retention_policy_complete(self, db_conn: sqlite3.Connection) -> None:
        rows = db_conn.execute("SELECT table_name FROM retention_policy").fetchall()
        tables = {r[0] for r in rows}
        expected = {"signals", "signals_1s", "signals_1m", "logs",
                    "events", "event_snapshots", "trips", "digest_daily"}
        assert expected.issubset(tables)

    def test_signals_table_columns(self, db_conn: sqlite3.Connection) -> None:
        info = db_conn.execute("PRAGMA table_info(signals)").fetchall()
        cols = {row[1] for row in info}
        assert cols == {"ts", "source", "signal", "value", "unit"}
