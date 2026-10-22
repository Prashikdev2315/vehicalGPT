"""Test read-only database connections."""
from __future__ import annotations

import sqlite3
from pathlib import Path
import pytest

from store.db import init_db
from store.ro_db import get_readonly_connection


class TestReadOnlyDB:
    def test_readonly_connection_reads_succeed(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test_ro.db"
        schema_path = Path("docs/schema.sql")
        conn = init_db(db_path, schema_path)
        conn.execute("INSERT INTO events (id, ts_start, type, severity, source) VALUES (1, 1000, 'test_event', 'info', 'can')")
        conn.commit()
        conn.close()

        # Connect with readonly helper
        ro_conn = get_readonly_connection(db_path)
        row = ro_conn.execute("SELECT id, type FROM events WHERE id = 1").fetchone()
        assert row is not None
        assert row["type"] == "test_event"
        ro_conn.close()

    def test_readonly_connection_writes_fail(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test_ro.db"
        schema_path = Path("docs/schema.sql")
        conn = init_db(db_path, schema_path)
        conn.close()

        ro_conn = get_readonly_connection(db_path)
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            ro_conn.execute("INSERT INTO events (id, ts_start, type, severity) VALUES (2, 2000, 'bad', 'info')")

        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            ro_conn.execute("DROP TABLE events")

        ro_conn.close()
