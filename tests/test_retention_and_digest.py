"""Tests for incremental daily digest and retention engine."""
from __future__ import annotations

import sqlite3
from pathlib import Path
import pytest

from insight.retention import apply_retention_policy
from store.digest import compute_daily_digest, recompute_and_store_digest


def test_digest_equivalence_on_vehicle_db():
    """Verify compute_daily_digest exactly matches simulation generator's digest_daily table."""
    conn = sqlite3.connect("data/vehicle.db")
    cur = conn.cursor()

    days = [r[0] for r in cur.execute("SELECT DISTINCT day FROM digest_daily ORDER BY day").fetchall()]
    assert len(days) == 28, f"Expected 28 days of digest data, got {len(days)}"

    for d in days:
        computed = compute_daily_digest(conn, d)
        assert computed is not None, f"Expected non-null computed digest for {d}"

        cur.execute("SELECT value FROM digest_daily WHERE day = ? AND metric = 'energy_per_km'", (d,))
        db_epk = cur.fetchone()[0]

        cur.execute("SELECT value FROM digest_daily WHERE day = ? AND metric = 'range_per_charge'", (d,))
        db_rpc = cur.fetchone()[0]

        assert abs(computed["energy_per_km"] - db_epk) < 1e-4, f"Mismatch in EPK for {d}: {computed['energy_per_km']} vs {db_epk}"
        assert abs(computed["range_per_charge"] - db_rpc) < 1e-4, f"Mismatch in RPC for {d}: {computed['range_per_charge']} vs {db_rpc}"

    conn.close()


def test_recompute_and_store_digest(tmp_path):
    """Verify recompute_and_store_digest writes valid rows to digest_daily."""
    db_file = tmp_path / "test_digest.db"
    conn = sqlite3.connect(db_file)
    cur = conn.cursor()

    # Create trips and digest_daily
    cur.execute("""
        CREATE TABLE trips (
            id INTEGER PRIMARY KEY,
            ts_start INTEGER,
            ts_end INTEGER,
            distance_km REAL,
            energy_kwh REAL,
            fuel_l REAL,
            avg_speed_kph REAL,
            city_share REAL,
            highway_share REAL,
            avg_ambient_c REAL,
            hvac_energy_kwh REAL
        )
    """)
    cur.execute("""
        CREATE TABLE digest_daily (
            day TEXT NOT NULL,
            metric TEXT NOT NULL,
            value REAL NOT NULL,
            n_trips INTEGER,
            PRIMARY KEY (day, metric)
        )
    """)

    # Insert 2 trips on 2026-10-27 (epoch ~1793040000000)
    # 2026-10-27 10:00:00 Asia/Kolkata is 1793076000000
    t1_start = 1793076000000
    t1_end = t1_start + 1800000
    t2_start = t1_end + 3600000
    t2_end = t2_start + 1800000

    cur.execute("INSERT INTO trips VALUES (1, ?, ?, 20.0, 2.0, 0, 40.0, 0.5, 0.5, 25.0, 0.2)", (t1_start, t1_end))
    cur.execute("INSERT INTO trips VALUES (2, ?, ?, 30.0, 3.0, 0, 50.0, 0.5, 0.5, 24.0, 0.3)", (t2_start, t2_end))
    conn.commit()

    ok = recompute_and_store_digest(conn, "2026-10-27")
    assert ok is True

    # 50 km total, 5.0 kWh total -> 100 Wh/km -> 600.0 km range
    cur.execute("SELECT metric, value, n_trips FROM digest_daily WHERE day = '2026-10-27' ORDER BY metric")
    rows = cur.fetchall()
    assert len(rows) == 2
    assert rows[0][0] == "energy_per_km"
    assert rows[0][1] == pytest.approx(100.0)
    assert rows[0][2] == 2

    assert rows[1][0] == "range_per_charge"
    assert rows[1][1] == pytest.approx(600.0)
    assert rows[1][2] == 2
    conn.close()


def test_retention_policy_virtual_clock(tmp_path):
    """Verify retention downsampling and pruning driven by retention_policy table."""
    db_file = tmp_path / "test_retention.db"
    conn = sqlite3.connect(db_file)
    cur = conn.cursor()

    # Create tables
    cur.execute("CREATE TABLE signals (ts INTEGER, source TEXT, signal TEXT, value REAL, unit TEXT)")
    cur.execute("CREATE TABLE signals_1s (ts INTEGER, signal TEXT, avg REAL, min REAL, max REAL, n INTEGER, PRIMARY KEY (signal, ts))")
    cur.execute("CREATE TABLE signals_1m (ts INTEGER, signal TEXT, avg REAL, min REAL, max REAL, n INTEGER, PRIMARY KEY (signal, ts))")
    cur.execute("CREATE TABLE logs (id INTEGER PRIMARY KEY, ts INTEGER, source TEXT, level TEXT, template_id INTEGER, message TEXT)")
    cur.execute("CREATE TABLE events (id INTEGER PRIMARY KEY, ts_start INTEGER, ts_end INTEGER, type TEXT, source TEXT, severity TEXT, payload TEXT)")
    cur.execute("CREATE TABLE event_snapshots (event_id INTEGER, ts INTEGER, signal TEXT, value REAL, PRIMARY KEY (event_id, signal, ts))")
    cur.execute("CREATE TABLE retention_policy (table_name TEXT PRIMARY KEY, keep_days INTEGER, max_bytes INTEGER)")

    # Standard policy: signals=2d, signals_1s=7d, signals_1m=90d, logs=30d
    cur.execute("INSERT INTO retention_policy VALUES ('signals', 2, NULL)")
    cur.execute("INSERT INTO retention_policy VALUES ('signals_1s', 7, NULL)")
    cur.execute("INSERT INTO retention_policy VALUES ('signals_1m', 90, NULL)")
    cur.execute("INSERT INTO retention_policy VALUES ('logs', 30, NULL)")
    cur.execute("INSERT INTO retention_policy VALUES ('events', NULL, NULL)")
    cur.execute("INSERT INTO retention_policy VALUES ('event_snapshots', NULL, NULL)")

    # Populate timestamps relative to reference now T0 = 100 * 86400 * 1000
    day_ms = 86400 * 1000
    t_now = 100 * day_ms

    # 1. signals: 1 row at t_now - 1 day (should keep), 1 row at t_now - 3 days (should prune)
    cur.execute("INSERT INTO signals VALUES (?, 'can', 'soc', 80.0, '%')", (t_now - 1 * day_ms,))
    cur.execute("INSERT INTO signals VALUES (?, 'can', 'soc', 80.0, '%')", (t_now - 3 * day_ms,))

    # 2. signals_1s: 1 row at t_now - 5 days (keep), 1 row at t_now - 8 days (prune)
    cur.execute("INSERT INTO signals_1s VALUES (?, 'soc', 80.0, 80.0, 80.0, 1)", (t_now - 5 * day_ms,))
    cur.execute("INSERT INTO signals_1s VALUES (?, 'soc', 80.0, 80.0, 80.0, 1)", (t_now - 8 * day_ms,))

    # 3. signals_1m: 1 row at t_now - 50 days (keep), 1 row at t_now - 95 days (prune)
    cur.execute("INSERT INTO signals_1m VALUES (?, 'soc', 80.0, 80.0, 80.0, 60)", (t_now - 50 * day_ms,))
    cur.execute("INSERT INTO signals_1m VALUES (?, 'soc', 80.0, 80.0, 80.0, 60)", (t_now - 95 * day_ms,))

    # 4. logs: 1 row at t_now - 20 days (keep), 1 row at t_now - 35 days (prune)
    cur.execute("INSERT INTO logs VALUES (1, ?, 'qnx', 'info', 1, 'ok')", (t_now - 20 * day_ms,))
    cur.execute("INSERT INTO logs VALUES (2, ?, 'qnx', 'info', 1, 'old')", (t_now - 35 * day_ms,))

    # 5. events and event_snapshots: event 1 exists, event 2 deleted (snapshot orphaned)
    cur.execute("INSERT INTO events VALUES (1, ?, ?, 'battery_overtemp_warning', 'can', 'critical', '{}')", (t_now - 10 * day_ms, t_now - 10 * day_ms + 60000))
    cur.execute("INSERT INTO event_snapshots VALUES (1, ?, 'pack_temp', 45.0)", (t_now - 10 * day_ms,))
    cur.execute("INSERT INTO event_snapshots VALUES (2, ?, 'pack_temp', 45.0)", (t_now - 10 * day_ms,)) # orphan
    conn.commit()

    report = apply_retention_policy(conn, ref_time_ms=t_now, vacuum=True)

    # Check pruned counts
    assert report["pruned"]["signals"] == 1
    assert report["pruned"]["signals_1s"] == 1
    assert report["pruned"]["signals_1m"] == 1
    assert report["pruned"]["logs"] == 1
    assert report["pruned"].get("event_snapshots_orphans") == 1

    # Verify surviving counts
    assert cur.execute("SELECT COUNT(*) FROM signals").fetchone()[0] == 1
    assert cur.execute("SELECT COUNT(*) FROM signals_1s").fetchone()[0] == 1
    assert cur.execute("SELECT COUNT(*) FROM signals_1m").fetchone()[0] == 1
    assert cur.execute("SELECT COUNT(*) FROM logs").fetchone()[0] == 1
    assert cur.execute("SELECT COUNT(*) FROM event_snapshots").fetchone()[0] == 1

    conn.close()
