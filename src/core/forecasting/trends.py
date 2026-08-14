"""Pure-Python trend estimation (Core domain forecasting).

Core Isolation invariant: no numpy. Implements a closed-form least-squares
slope estimator in standard-library Python, returning the hourly trend
(value change per hour) for a single vital channel.
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

SECONDS_PER_HOUR: float = 3600.0


def compute_channel_slope(
    timestamps: list[float],
    values: list[float],
) -> Optional[float]:
    """Least-squares slope of ``values`` over ``timestamps``.

    Args:
        timestamps: observation epoch seconds (monotonic not required).
        values: aligned vital values.

    Returns:
        Trend in value-per-hour, or ``None`` if undefined.

    Raises:
        ValueError: if fewer than 2 data points are supplied.
    """
    if len(timestamps) != len(values):
        raise ValueError("timestamps and values must be the same length")
    if len(timestamps) < 2:
        raise ValueError("at least 2 data points are required to compute a slope")

    # Convert epoch seconds -> hours to express the slope per hour.
    t_hours: list[float] = [ts / SECONDS_PER_HOUR for ts in timestamps]
    n = len(t_hours)
    t_mean = sum(t_hours) / n
    v_mean = sum(values) / n

    denom = sum((ti - t_mean) ** 2 for ti in t_hours)
    if denom == 0:
        logger.debug("Zero temporal variance; slope undefined")
        return 0.0

    slope = sum((ti - t_mean) * (vi - v_mean) for ti, vi in zip(t_hours, values)) / denom
    return round(slope, 4)
