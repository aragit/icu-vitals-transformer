"""Deterministic forecasting with trend extrapolation (Core domain forecasting).

Core Isolation invariant: pure Python + pydantic only.

Projects a ``VitalSignsWindow`` forward across a horizon using linear trend
extrapolation with clinical bound clamping and growing uncertainty. When no
trend is supplied the projection is a flat-line (forecast == current), matching
the Phase 0 baseline contract (docs/BASELINE.md §5.3).

Note: the Phase 0 baseline used a *truthiness* guard for uncertainty bounds
(a ``0.0`` vital produced ``None`` bounds). This module preserves that
behavior exactly so the Phase 0 test suite stays green, but expresses it with
explicit guards so strict mypy is satisfied without ``operator`` ignores.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, overload

from src.core.domain.forecast import ForecastResult
from src.core.domain.vitals import VitalSignsWindow

logger = logging.getLogger(__name__)

# Clinical hard bounds for clamping.
BOUNDS: dict[str, tuple[float, float]] = {
    "heart_rate": (0.0, 300.0),
    "systolic_bp": (0.0, 300.0),
    "diastolic_bp": (0.0, 200.0),
    "spo2": (0.0, 100.0),
    "respiratory_rate": (0.0, 60.0),
    "temperature": (30.0, 45.0),
}

NUMERIC_FIELDS: tuple[str, ...] = (
    "heart_rate",
    "systolic_bp",
    "diastolic_bp",
    "spo2",
    "respiratory_rate",
    "temperature",
)


def clamp(field: str, value: Optional[float]) -> Optional[float]:
    """Clamp a value to its clinical bounds (``None`` passes through)."""
    if value is None:
        return None
    low, high = BOUNDS.get(field, (0.0, 999.0))
    return round(max(low, min(high, value)), 2)


@overload
def extrapolate_value(
    current: None, horizon_minutes: int, trend_per_hour: float = ...
) -> None: ...


@overload
def extrapolate_value(
    current: float, horizon_minutes: int, trend_per_hour: float = ...
) -> float: ...


def extrapolate_value(
    current: Optional[float],
    horizon_minutes: int,
    trend_per_hour: float = 0.0,
) -> Optional[float]:
    """Extrapolate a vital value using linear trend (value change per hour).

    ``None`` input yields ``None``; otherwise ``current + trend_per_hour*hours``.
    """
    if current is None:
        return None
    hours = horizon_minutes / 60.0
    return round(current + (trend_per_hour * hours), 2)


def compute_uncertainty(horizon_minutes: int) -> float:
    """Uncertainty widens linearly with horizon: 2.0 * (1 + 0.1 * h/60)."""
    base = 2.0
    multiplier = horizon_minutes / 60.0
    return round(base * (1 + 0.1 * multiplier), 2)


def _channel_value(window: VitalSignsWindow, field: str) -> Optional[float]:
    """Read a numeric channel as a float (or None), typing the getattr."""
    raw = getattr(window, field)
    if isinstance(raw, bool):
        return None
    return raw if isinstance(raw, (int, float)) else None


def _freshness_seconds(window: VitalSignsWindow) -> int:
    end = window.window_end
    now = datetime.now(timezone.utc)
    if end.tzinfo is None:
        # Legacy callers pass naive UTC timestamps; assume UTC for the delta.
        end = end.replace(tzinfo=timezone.utc)
    delta = now - end
    return max(0, int(delta.total_seconds()))


def forecast_vitals(
    current_window: VitalSignsWindow,
    horizon_minutes: int,
    trend_per_hour: Optional[dict[str, float]] = None,
) -> ForecastResult:
    """Generate a deterministic forecast from current vitals."""
    trend = trend_per_hour or {}
    uncertainty = compute_uncertainty(horizon_minutes)

    def _extrapolate(field: str) -> Optional[float]:
        current = _channel_value(current_window, field)
        return clamp(field, extrapolate_value(current, horizon_minutes, trend.get(field, 0.0)))

    def _bound(field: str, sign: float) -> Optional[float]:
        current = _channel_value(current_window, field)
        # Truthiness guard preserves the Phase 0 baseline: a falsy (None or 0.0)
        # channel yields None bounds.
        if not current:
            return None
        projected = extrapolate_value(current, horizon_minutes, trend.get(field, 0.0))
        return clamp(field, projected + sign * uncertainty)

    forecasted = VitalSignsWindow(
        patient_id=current_window.patient_id,
        window_start=current_window.window_end,
        window_end=current_window.window_end + timedelta(minutes=horizon_minutes),
        heart_rate=_extrapolate("heart_rate"),
        systolic_bp=_extrapolate("systolic_bp"),
        diastolic_bp=_extrapolate("diastolic_bp"),
        spo2=_extrapolate("spo2"),
        respiratory_rate=_extrapolate("respiratory_rate"),
        temperature=_extrapolate("temperature"),
        avpu=current_window.avpu,
    )

    lower = VitalSignsWindow(
        patient_id=current_window.patient_id,
        window_start=forecasted.window_start,
        window_end=forecasted.window_end,
        heart_rate=_bound("heart_rate", -1.0),
        systolic_bp=_bound("systolic_bp", -1.0),
        diastolic_bp=_bound("diastolic_bp", -1.0),
        spo2=_bound("spo2", -1.0),
        respiratory_rate=_bound("respiratory_rate", -1.0),
        temperature=_bound("temperature", -1.0),
        avpu=current_window.avpu,
    )

    upper = VitalSignsWindow(
        patient_id=current_window.patient_id,
        window_start=forecasted.window_start,
        window_end=forecasted.window_end,
        heart_rate=_bound("heart_rate", 1.0),
        systolic_bp=_bound("systolic_bp", 1.0),
        diastolic_bp=_bound("diastolic_bp", 1.0),
        spo2=_bound("spo2", 1.0),
        respiratory_rate=_bound("respiratory_rate", 1.0),
        temperature=_bound("temperature", 1.0),
        avpu=current_window.avpu,
    )

    freshness = _freshness_seconds(current_window)
    stale = freshness > STALE_DATA_THRESHOLD_SECONDS

    contributing_factors: list[str] = []
    if stale:
        contributing_factors.append("stale_data_warning")
    for field in NUMERIC_FIELDS:
        if trend.get(field, 0.0) != 0.0 and _channel_value(current_window, field) is not None:
            contributing_factors.append(f"{field}_trend")

    logger.info(
        "Forecast generated for %s at %smin horizon",
        current_window.patient_id,
        horizon_minutes,
    )

    return ForecastResult(
        patient_id=current_window.patient_id,
        horizon_minutes=horizon_minutes,
        forecasted_vitals=forecasted,
        uncertainty_lower=lower,
        uncertainty_upper=upper,
        deterioration_index=0.0,
        severity="NORMAL",
        generated_at=datetime.now(timezone.utc),
        data_freshness_seconds=freshness,
        stale_data_warning=stale,
        contributing_factors=contributing_factors,
    )


STALE_DATA_THRESHOLD_SECONDS: int = 300
