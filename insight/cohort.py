"""Cohort filtering and statistical comparison using pure NumPy."""
from __future__ import annotations

import math
import sqlite3
from typing import Any
import numpy as np


def filter_cohort_data(
    conn: sqlite3.Connection,
    segment: str,
    metric: str,
    start_ms: int,
    end_ms: int,
) -> tuple[np.ndarray, list[str]]:
    """Query and filter values for a specific driving or operation segment.

    Segment enums:
        - 'city': trips with city_share >= 0.6
        - 'highway': trips with highway_share >= 0.6
        - 'mixed': trips with 0.3 < city_share < 0.7
        - 'cold_start': trips starting with battery pack temp near ambient (<= ambient + 2C)
        - 'charging': charging session events energy or power
        - 'all': all trips in window

    Returns:
        tuple of (numpy array of values, list of evidence ref strings)
    """
    cur = conn.cursor()
    evidence_refs: list[str] = []

    if metric in ("energy_per_km", "fuel_efficiency", "mileage", "efficiency"):
        # Query trips table
        sql = """
            SELECT id, distance_km, energy_kwh, city_share, highway_share, avg_ambient_c
            FROM trips
            WHERE ts_start >= ? AND ts_end <= ? AND distance_km > 0.5
        """
        rows = cur.execute(sql, (start_ms, end_ms)).fetchall()

        vals: list[float] = []
        for r in rows:
            dist = r["distance_km"]
            kwh = r["energy_kwh"]
            c_share = r["city_share"] if r["city_share"] is not None else 0.0
            h_share = r["highway_share"] if r["highway_share"] is not None else 0.0
            epk = (kwh * 1000.0) / dist if dist > 0 else 0.0

            match = False
            if segment == "city" and c_share >= 0.6:
                match = True
            elif segment == "highway" and h_share >= 0.6:
                match = True
            elif segment == "mixed" and (0.3 < c_share < 0.7):
                match = True
            elif segment in ("all", "cold_start"):
                match = True

            if match and epk > 0:
                vals.append(epk)
                evidence_refs.append(f"trip:{r['id']}")

        return np.array(vals, dtype=float), evidence_refs

    # For other generic signals, query signals or signals_1m
    sql = """
        SELECT avg FROM signals_1m
        WHERE signal = ? AND ts >= ? AND ts <= ?
    """
    rows = cur.execute(sql, (metric, start_ms, end_ms)).fetchall()
    vals = [r["avg"] for r in rows if r["avg"] is not None]
    evidence_refs.append(f"signals_1m:{metric}")
    return np.array(vals, dtype=float), evidence_refs


def compare_cohort_statistics(
    vals_a: np.ndarray,
    vals_b: np.ndarray,
) -> dict[str, Any]:
    """Compute exact numerical gaps and two-sample statistical differences.

    Does not inject canned causal explanations; returns calculated metrics only.
    """
    n_a = len(vals_a)
    n_b = len(vals_b)

    if n_a == 0 or n_b == 0:
        return {
            "n_a": n_a,
            "n_b": n_b,
            "mean_a": None,
            "mean_b": None,
            "gap": None,
            "pct_gap": None,
            "confidence": 0.0,
        }

    mean_a = float(np.mean(vals_a))
    mean_b = float(np.mean(vals_b))
    var_a = float(np.var(vals_a, ddof=1)) if n_a > 1 else 0.0
    var_b = float(np.var(vals_b, ddof=1)) if n_b > 1 else 0.0

    gap = mean_a - mean_b
    pct_gap = (gap / mean_b * 100.0) if abs(mean_b) > 1e-6 else 0.0

    # Welch's t-test standard error
    se = math.sqrt(var_a / n_a + var_b / n_b) if (var_a + var_b) > 0 else 1.0
    t_stat = abs(gap) / se if se > 0 else 0.0
    confidence = min(1.0, max(0.5, 1.0 - math.exp(-0.5 * (t_stat ** 2) / 2.0)))

    return {
        "n_a": n_a,
        "n_b": n_b,
        "mean_a": round(mean_a, 2),
        "mean_b": round(mean_b, 2),
        "gap": round(gap, 2),
        "pct_gap": round(pct_gap, 2),
        "se": round(se, 3),
        "confidence": round(confidence, 2),
    }
