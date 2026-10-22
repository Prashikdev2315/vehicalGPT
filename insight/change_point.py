"""Pure NumPy change-point and step detection routines.

Finds the point in time when a metric experienced the largest sustained transition
(change-point), rather than an isolated noisy peak or trough.
"""
from __future__ import annotations

import math
from typing import Any
import numpy as np


def detect_largest_change_point(
    dates: list[str],
    values: list[float],
    timestamps: list[int],
    direction: str = "drop",
    min_window: int = 2,
) -> dict[str, Any] | None:
    """Find the date/timestamp where the largest sustained change occurred.

    Args:
        dates: List of ISO date strings (ordered chronologically).
        values: List of metric float values.
        timestamps: List of epoch ms timestamps.
        direction: 'drop' (biggest negative shift), 'rise' (biggest positive shift),
                   or 'either' (largest absolute shift).
        min_window: Minimum window size on each side of the candidate split.

    Returns:
        dict with details of the change point, or None if insufficient points.
    """
    n = len(values)
    if n < 2 * min_window:
        return None

    y = np.array(values, dtype=float)
    best_idx = -1
    best_score = -float("inf")
    best_diff = 0.0
    best_mean_before = 0.0
    best_mean_after = 0.0

    # Test all possible split points k where both sides have at least min_window points
    for k in range(min_window, n - min_window + 1):
        before = y[:k]
        after = y[k:]
        mean_b = float(np.mean(before))
        mean_a = float(np.mean(after))
        diff = mean_a - mean_b  # negative = drop, positive = rise

        if direction == "drop":
            score = -diff  # larger drop -> higher score
        elif direction == "rise":
            score = diff   # larger rise -> higher score
        else:
            score = abs(diff)

        if score > best_score:
            best_score = score
            best_idx = k
            best_diff = diff
            best_mean_before = mean_b
            best_mean_after = mean_a

    if best_idx < 0:
        return None

    change_date = dates[best_idx]
    change_ts = timestamps[best_idx]
    pct_change = (best_diff / best_mean_before * 100.0) if abs(best_mean_before) > 1e-6 else 0.0

    # Welch's t-test approximation using pure numpy
    before = y[:best_idx]
    after = y[best_idx:]
    var_b = float(np.var(before, ddof=1)) if len(before) > 1 else 0.0
    var_a = float(np.var(after, ddof=1)) if len(after) > 1 else 0.0
    se = math.sqrt(var_b / len(before) + var_a / len(after)) if (var_b + var_a) > 0 else 1.0
    t_stat = abs(best_diff) / se if se > 0 else 0.0
    # Approximate confidence from t_stat
    confidence = min(1.0, max(0.5, 1.0 - math.exp(-0.5 * (t_stat ** 2) / 2.0)))

    return {
        "index": best_idx,
        "date": change_date,
        "timestamp": change_ts,
        "mean_before": round(best_mean_before, 2),
        "mean_after": round(best_mean_after, 2),
        "delta": round(best_diff, 2),
        "pct_change": round(pct_change, 2),
        "confidence": round(confidence, 2),
        "n_before": len(before),
        "n_after": len(after),
    }
