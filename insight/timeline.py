"""Algorithmic pre-event deviation onset detection and timeline sequencing."""
from __future__ import annotations

import math
from typing import Any
import numpy as np


def detect_signal_deviation_onset(
    timestamps: list[int],
    values: list[float],
    baseline_fraction: float = 0.05,
    min_deviation: float = 0.5,
) -> dict[str, Any] | None:
    """Compute baseline mu, sigma and identify the exact timestamp where deviation begins.

    Args:
        timestamps: Chronologically sorted millisecond timestamps.
        values: Corresponding signal values.
        baseline_fraction: Fraction of early lookback to establish normal baseline.
        min_deviation: Minimum absolute deviation threshold to avoid noise false-positives.

    Returns:
        dict with onset details (onset_ts, baseline_mean, final_val, delta, seconds_before)
        or None if no significant deviation is found.
    """
    n = len(values)
    if n < 10:
        return None

    y = np.array(values, dtype=float)
    t = np.array(timestamps, dtype=np.int64)

    # Determine baseline cutoff: prefer time-based if timestamps span > 0
    t_span = t[-1] - t[0]
    if t_span > 0:
        t_base_end = t[0] + int(t_span * baseline_fraction)
        base_mask = t <= t_base_end
        if np.sum(base_mask) < 3:
            n_base = max(3, int(n * baseline_fraction))
            base_vals = y[:n_base]
            base_end_idx = n_base
        else:
            base_vals = y[base_mask]
            base_end_idx = int(np.where(base_mask)[0][-1]) + 1
    else:
        n_base = max(3, int(n * baseline_fraction))
        base_vals = y[:n_base]
        base_end_idx = n_base

    mu0 = float(np.mean(base_vals))
    sigma0 = float(np.std(base_vals))

    threshold = max(3.0 * sigma0, min_deviation)

    # Search for first sustained deviation (>= 3 consecutive points)
    onset_idx = -1
    for i in range(base_end_idx, n - 2):
        if (abs(y[i] - mu0) >= threshold and
                abs(y[i + 1] - mu0) >= threshold and
                abs(y[i + 2] - mu0) >= threshold):
            onset_idx = i
            break

    if onset_idx < 0:
        return None

    onset_ts = int(t[onset_idx])
    final_val = float(y[-1])
    delta = final_val - mu0

    return {
        "onset_ts": onset_ts,
        "baseline_mean": round(mu0, 2),
        "final_val": round(final_val, 2),
        "delta": round(delta, 2),
        "pct_change": round((delta / mu0 * 100.0) if abs(mu0) > 1e-6 else 0.0, 1),
    }
