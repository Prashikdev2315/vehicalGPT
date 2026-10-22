"""Incremental Daily Digest Computer.

Computes daily roll-up metrics (energy_per_km, range_per_charge) from trips table
using vehicle timezone boundaries.
"""
from __future__ import annotations

import sqlite3
from typing import Any

from tools.time_parser import parse_iso_to_epoch_ms


def compute_daily_digest(
    conn: sqlite3.Connection,
    day_str: str,
    tz_name: str = "Asia/Kolkata",
    battery_capacity_kwh: float = 60.0,
) -> dict[str, Any] | None:
    """Compute energy_per_km and range_per_charge for a given calendar day from trips.

    Args:
        conn: SQLite connection.
        day_str: 'YYYY-MM-DD' calendar date.
        tz_name: Timezone name for midnight-to-midnight boundary.
        battery_capacity_kwh: Nominal pack capacity.

    Returns:
        dict with metrics and trip count, or None if no trips occurred on day.
    """
    t_start = parse_iso_to_epoch_ms(day_str, tz_name=tz_name, end_of_day=False)
    t_end = parse_iso_to_epoch_ms(day_str, tz_name=tz_name, end_of_day=True)

    cur = conn.cursor()
    row = cur.execute(
        """
        SELECT
            COUNT(*),
            COALESCE(SUM(distance_km), 0.0),
            COALESCE(SUM(energy_kwh), 0.0)
        FROM trips
        WHERE ts_start >= ? AND ts_start <= ?
        """,
        (t_start, t_end),
    ).fetchone()

    n_trips, dist_km, energy_kwh = row
    if n_trips == 0 or dist_km <= 0.0:
        return None

    # day_energy_wh / day_distance_km
    energy_wh = energy_kwh * 1000.0
    epk = energy_wh / dist_km
    rpc = (battery_capacity_kwh * 1000.0 / epk) if epk > 1.0 else 0.0

    return {
        "day": day_str,
        "energy_per_km": epk,
        "range_per_charge": rpc,
        "n_trips": n_trips,
        "distance_km": dist_km,
        "energy_kwh": energy_kwh,
    }


def recompute_and_store_digest(
    conn: sqlite3.Connection,
    day_str: str,
    tz_name: str = "Asia/Kolkata",
    battery_capacity_kwh: float = 60.0,
) -> bool:
    """Recompute daily digest from trips and write to digest_daily.

    Returns True if metrics were computed and stored, False if no trips on that day.
    """
    res = compute_daily_digest(
        conn, day_str, tz_name=tz_name, battery_capacity_kwh=battery_capacity_kwh
    )
    if res is None:
        return False

    with conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO digest_daily (day, metric, value, n_trips)
            VALUES (?, 'energy_per_km', ?, ?)
            """,
            (day_str, res["energy_per_km"], res["n_trips"]),
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO digest_daily (day, metric, value, n_trips)
            VALUES (?, 'range_per_charge', ?, ?)
            """,
            (day_str, res["range_per_charge"], res["n_trips"]),
        )
    return True
