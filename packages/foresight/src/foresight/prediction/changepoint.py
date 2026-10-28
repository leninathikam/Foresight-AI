"""CUSUM change-point detection on standardized residual signals."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class CusumResult:
    alarm_index: int | None
    direction: str | None  # "up" | "down"
    positive: np.ndarray
    negative: np.ndarray


def cusum(
    series: np.ndarray,
    mean: float,
    std: float,
    drift: float = 0.5,
    threshold: float = 8.0,
    skip: int = 0,
    upward_only: bool = False,
) -> CusumResult:
    """Page's CUSUM. ``drift`` (k) and ``threshold`` (h) are in units of ``std``.

    The first ``skip`` points (start-up transient) do not accumulate. With ``upward_only`` the
    downward sum is still reported but never raises an alarm.
    Returns the first index where an alarming cumulative sum exceeds ``threshold``.
    """
    z = (np.asarray(series, dtype=float) - mean) / max(std, 1e-9)
    z = np.nan_to_num(z, nan=0.0)
    z[:skip] = 0.0
    pos = np.zeros_like(z)
    neg = np.zeros_like(z)
    alarm, direction = None, None
    for i, zi in enumerate(z):
        prev_p = pos[i - 1] if i else 0.0
        prev_n = neg[i - 1] if i else 0.0
        pos[i] = max(0.0, prev_p + zi - drift) if i >= skip else 0.0
        neg[i] = max(0.0, prev_n - zi - drift) if i >= skip else 0.0
        if alarm is None:
            if pos[i] > threshold:
                alarm, direction = i, "up"
            elif not upward_only and neg[i] > threshold:
                alarm, direction = i, "down"
    return CusumResult(alarm_index=alarm, direction=direction, positive=pos, negative=neg)
