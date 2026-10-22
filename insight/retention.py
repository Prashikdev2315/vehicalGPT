"""Data retention and downsampling engine driven by retention_policy table."""
from __future__ import annotations

import sqlite3
import time
from typing import Any


def apply_retention_policy(
    conn: sqlite3.Connection,
    ref_time_ms: int | None = None,
    vacuum: bool = False,
) -> dict[str, Any]:
    """Execute retention and downsampling rules defined in the retention_policy table.

    Args:
        conn: SQLite connection (must have write privileges).
        ref_time_ms: Reference 'now' epoch ms for virtual clock testing.
                     If None, defaults to current system time or max timestamp in signals.
        vacuum: If True, execute VACUUM after pruning to reclaim disk space.

    Returns:
        Summary report containing pruned row counts and cutoffs per table.
    """
    cur = conn.cursor()

    if ref_time_ms is None:
        # Determine latest timestamp from signals, or fallback to current wall time
        cur.execute("SELECT MAX(ts) FROM signals")
        row = cur.fetchone()
        if row and row[0] is not None:
            ref_time_ms = int(row[0])
        else:
            ref_time_ms = int(time.time() * 1000)

    # Read retention policy from database
    cur.execute("SELECT table_name, keep_days, max_bytes FROM retention_policy")
    policies = cur.fetchall()

    report: dict[str, Any] = {
        "ref_time_ms": ref_time_ms,
        "pruned": {},
        "cutoffs": {},
    }

    with conn:
        for tbl, keep_days, _ in policies:
            if keep_days is not None:
                cutoff = ref_time_ms - (keep_days * 86400 * 1000)
                report["cutoffs"][tbl] = cutoff

                if tbl in ("signals", "signals_1s", "signals_1m", "logs"):
                    cur.execute(f"DELETE FROM {tbl} WHERE ts < ?", (cutoff,))
                    report["pruned"][tbl] = cur.rowcount

        # Clean event_snapshots whose parent event no longer exists
        cur.execute("DELETE FROM event_snapshots WHERE event_id NOT IN (SELECT id FROM events)")
        orphan_snaps = cur.rowcount
        if orphan_snaps > 0:
            report["pruned"]["event_snapshots_orphans"] = orphan_snaps

    if vacuum:
        conn.execute("VACUUM")

    return report
