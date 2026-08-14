"""Clinical safety shell (Core domain safety).

Core Isolation invariant: pure Python + pydantic/loguru-free. Uses stdlib
``logging`` only.

``SafetyShell`` is a decorator over any ``ForecastBackend``: it clamps
projected vitals to hard physiological bounds, enforces
``lower <= forecasted <= upper`` ordering, honors a 5-minute data-freshness
threshold, and degrades gracefully to a flat-line projection when the inner
backend raises.
"""

from __future__ import annotations

import logging
from typing import Callable

from src.core.domain.forecast import ForecastResult
from src.core.domain.vitals import VitalSignsWindow
from src.core.forecasting.forecaster import (
    NUMERIC_FIELDS,
    clamp,
    forecast_vitals,
)
from src.ports.forecaster import ForecastBackend

logger = logging.getLogger(__name__)

STALE_DATA_THRESHOLD_SECONDS: int = 300


def _clamp_window(window: VitalSignsWindow) -> VitalSignsWindow:
    """Return a copy of ``window`` with each numeric channel clamped to BOUNDS."""
    return VitalSignsWindow(
        patient_id=window.patient_id,
        window_start=window.window_start,
        window_end=window.window_end,
        heart_rate=clamp("heart_rate", window.heart_rate),
        systolic_bp=clamp("systolic_bp", window.systolic_bp),
        diastolic_bp=clamp("diastolic_bp", window.diastolic_bp),
        spo2=clamp("spo2", window.spo2),
        respiratory_rate=clamp("respiratory_rate", window.respiratory_rate),
        temperature=clamp("temperature", window.temperature),
        avpu=window.avpu,
    )


class SafetyShell(ForecastBackend):
    """Decorator that sanitizes a wrapped ``ForecastBackend``'s output."""

    def __init__(
        self,
        inner: ForecastBackend,
        on_fallback: Callable[..., None] | None = None,
    ) -> None:
        self._inner = inner
        self._on_fallback = on_fallback

    async def forecast(
        self,
        window: VitalSignsWindow,
        horizon_minutes: int,
        trend_per_hour: dict[str, float],
    ) -> ForecastResult:
        try:
            result = await self._inner.forecast(window, horizon_minutes, trend_per_hour)
        except Exception as exc:  # noqa: BLE001 - safety fallback must not raise
            logger.critical(
                "Inner forecast backend failed (%s); falling back to flat-line "
                "deterministic projection.",
                exc,
            )
            if self._on_fallback is not None:
                self._on_fallback()
            result = forecast_vitals(window, horizon_minutes, {})
        return self.validate(result, window)

    def validate(
        self,
        result: ForecastResult,
        window: VitalSignsWindow,
    ) -> ForecastResult:
        # Clamp every projected window to physiological bounds.
        result.forecasted_vitals = _clamp_window(result.forecasted_vitals)
        result.uncertainty_lower = _clamp_window(result.uncertainty_lower)
        result.uncertainty_upper = _clamp_window(result.uncertainty_upper)

        # Enforce lower <= forecasted <= upper per channel.
        for field in NUMERIC_FIELDS:
            forecasted = getattr(result.forecasted_vitals, field)
            lower = getattr(result.uncertainty_lower, field)
            upper = getattr(result.uncertainty_upper, field)
            if forecasted is None:
                continue
            if lower is not None and lower > forecasted:
                setattr(result.uncertainty_lower, field, forecasted)
            if upper is not None and upper < forecasted:
                setattr(result.uncertainty_upper, field, forecasted)

        # Stale-data guard.
        if result.data_freshness_seconds > STALE_DATA_THRESHOLD_SECONDS:
            result.stale_data_warning = True
            if "stale_data_warning" not in result.contributing_factors:
                result.contributing_factors.append("stale_data_warning")

        logger.debug(
            "SafetyShell validated forecast for %s (freshness=%ss)",
            result.patient_id,
            result.data_freshness_seconds,
        )
        return result
