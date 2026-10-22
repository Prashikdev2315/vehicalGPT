"""Read-only SQLite connection provider for analytical tools.

Enforces freedom-from-interference and prevents any unintentional write operations
from the AI / analytics domain.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path


def get_readonly_connection(db_path: Path | str) -> sqlite3.Connection:
    """Open a strictly read-only connection to the SQLite database.

    Uses SQLite URI mode '?mode=ro' and sets 'PRAGMA query_only = ON'.
    Any mutation (INSERT, UPDATE, DELETE, DROP, CREATE) raises sqlite3.OperationalError.
    """
    path = Path(db_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Database not found: {path}")

    # Use URI format for read-only opening
    uri = f"file:{path.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=10.0)
    conn.execute("PRAGMA query_only = ON")
    conn.row_factory = sqlite3.Row
    return conn
