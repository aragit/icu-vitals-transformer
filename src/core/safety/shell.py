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
        on_stale_data: Callable[..., None] | None = None,
    ) -> None:
        self._inner = inner
        self._on_fallback = on_fallback
        self._on_stale_data = on_stale_data

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
        """Sanitize a forecast result **without mutating the caller's object**.

        Returns a deep-copied ``ForecastResult`` with projected vitals clamped
        to physiological bounds, lower/upper ordering enforced, and stale-data
        warnings attached. The input ``result`` is left untouched so upstream
        callers (e.g. the ensemble) can still read the raw, unclamped projection.
        """
        forecasted = _clamp_window(result.forecasted_vitals)
        lower = _clamp_window(result.uncertainty_lower)
        upper = _clamp_window(result.uncertainty_upper)

        # Enforce lower <= forecasted <= upper per channel on the copies.
        for field in NUMERIC_FIELDS:
            forecasted_val = getattr(forecasted, field)
            lower_val = getattr(lower, field)
            upper_val = getattr(upper, field)
            if forecasted_val is None:
                continue
            if lower_val is not None and lower_val > forecasted_val:
                lower = lower.model_copy(update={field: forecasted_val})
            if upper_val is not None and upper_val < forecasted_val:
                upper = upper.model_copy(update={field: forecasted_val})

        # Stale-data guard; derived from freshness, attached to a copy of factors.
        stale = result.data_freshness_seconds > STALE_DATA_THRESHOLD_SECONDS
        contributing_factors = list(result.contributing_factors)
        if stale and "stale_data_warning" not in contributing_factors:
            contributing_factors.append("stale_data_warning")
            if self._on_stale_data is not None:
                self._on_stale_data()

        logger.debug(
            "SafetyShell validated forecast for %s (freshness=%ss)",
            result.patient_id,
            result.data_freshness_seconds,
        )
        return result.model_copy(
            update={
                "forecasted_vitals": forecasted,
                "uncertainty_lower": lower,
                "uncertainty_upper": upper,
                "stale_data_warning": stale,
                "contributing_factors": contributing_factors,
            },
            deep=True,
        )
