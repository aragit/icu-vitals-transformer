"""Deterministic forecasting with trend extrapolation fallback.

No neural model required. Uses linear trend from recent windows
plus clinical uncertainty bounds.
"""

from datetime import datetime, timezone, timedelta
from typing import Optional

from loguru import logger

from src.models.vitals import VitalSignsWindow
from src.models.forecast import ForecastResult


# Clinical bounds for clamping
BOUNDS = {
    "heart_rate": (0, 300),
    "systolic_bp": (0, 300),
    "diastolic_bp": (0, 200),
    "spo2": (0, 100),
    "respiratory_rate": (0, 60),
    "temperature": (30, 45),
}


def _clamp(field: str, value: Optional[float]) -> Optional[float]:
    """Clamp value to clinical bounds."""
    if value is None:
        return None
    low, high = BOUNDS.get(field, (0, 999))
    return round(max(low, min(high, value)), 2)


def _extrapolate_value(current: Optional[float], horizon_minutes: int, trend_per_hour: float = 0.0) -> Optional[float]:
    """Extrapolate a vital sign value using linear trend."""
    if current is None:
        return None
    hours = horizon_minutes / 60.0
    return round(current + (trend_per_hour * hours), 2)


def _compute_uncertainty(horizon_minutes: int) -> float:
    """Wider uncertainty for longer horizons."""
    base = 2.0
    multiplier = horizon_minutes / 60.0
    return round(base * (1 + 0.1 * multiplier), 2)


def forecast_vitals(
    current_window: VitalSignsWindow,
    horizon_minutes: int,
    trend_per_hour: dict[str, float] | None = None,
) -> ForecastResult:
    """Generate deterministic forecast from current vitals."""
    trend = trend_per_hour or {}
    uncertainty = _compute_uncertainty(horizon_minutes)

    def _extrapolate(field: str) -> Optional[float]:
        return _clamp(field, _extrapolate_value(
            getattr(current_window, field),
            horizon_minutes,
            trend.get(field, 0.0),
        ))

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

    uncertainty_lower = VitalSignsWindow(
        patient_id=current_window.patient_id,
        window_start=forecasted.window_start,
        window_end=forecasted.window_end,
        heart_rate=_clamp("heart_rate", _extrapolate_value(current_window.heart_rate, horizon_minutes, trend.get("heart_rate", 0.0)) - uncertainty) if current_window.heart_rate else None,
        systolic_bp=_clamp("systolic_bp", _extrapolate_value(current_window.systolic_bp, horizon_minutes, trend.get("systolic_bp", 0.0)) - uncertainty) if current_window.systolic_bp else None,
        diastolic_bp=_clamp("diastolic_bp", _extrapolate_value(current_window.diastolic_bp, horizon_minutes, trend.get("diastolic_bp", 0.0)) - uncertainty) if current_window.diastolic_bp else None,
        spo2=_clamp("spo2", _extrapolate_value(current_window.spo2, horizon_minutes, trend.get("spo2", 0.0)) - uncertainty) if current_window.spo2 else None,
        respiratory_rate=_clamp("respiratory_rate", _extrapolate_value(current_window.respiratory_rate, horizon_minutes, trend.get("respiratory_rate", 0.0)) - uncertainty) if current_window.respiratory_rate else None,
        temperature=_clamp("temperature", _extrapolate_value(current_window.temperature, horizon_minutes, trend.get("temperature", 0.0)) - uncertainty) if current_window.temperature else None,
        avpu=current_window.avpu,
    )

    uncertainty_upper = VitalSignsWindow(
        patient_id=current_window.patient_id,
        window_start=forecasted.window_start,
        window_end=forecasted.window_end,
        heart_rate=_clamp("heart_rate", _extrapolate_value(current_window.heart_rate, horizon_minutes, trend.get("heart_rate", 0.0)) + uncertainty) if current_window.heart_rate else None,
        systolic_bp=_clamp("systolic_bp", _extrapolate_value(current_window.systolic_bp, horizon_minutes, trend.get("systolic_bp", 0.0)) + uncertainty) if current_window.systolic_bp else None,
        diastolic_bp=_clamp("diastolic_bp", _extrapolate_value(current_window.diastolic_bp, horizon_minutes, trend.get("diastolic_bp", 0.0)) + uncertainty) if current_window.diastolic_bp else None,
        spo2=_clamp("spo2", _extrapolate_value(current_window.spo2, horizon_minutes, trend.get("spo2", 0.0)) + uncertainty) if current_window.spo2 else None,
        respiratory_rate=_clamp("respiratory_rate", _extrapolate_value(current_window.respiratory_rate, horizon_minutes, trend.get("respiratory_rate", 0.0)) + uncertainty) if current_window.respiratory_rate else None,
        temperature=_clamp("temperature", _extrapolate_value(current_window.temperature, horizon_minutes, trend.get("temperature", 0.0)) + uncertainty) if current_window.temperature else None,
        avpu=current_window.avpu,
    )

    logger.info(f"Forecast generated for {current_window.patient_id} at {horizon_minutes}min horizon")

    return ForecastResult(
        patient_id=current_window.patient_id,
        horizon_minutes=horizon_minutes,
        forecasted_vitals=forecasted,
        uncertainty_lower=uncertainty_lower,
        uncertainty_upper=uncertainty_upper,
        deterioration_index=0.0,
        severity="NORMAL",
        generated_at=datetime.now(timezone.utc),
    )
