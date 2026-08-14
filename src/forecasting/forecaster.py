"""Legacy forecasting shim — delegates to the Core deterministic forecaster.

Phase 1 strangler-fig: canonical calculations live in
``src/core/forecasting/forecaster.py``. This shim preserves the legacy public
names (``BOUNDS``, ``_extrapolate_value``, ``_compute_uncertainty``,
``_clamp``, ``forecast_vitals``) and converts the Core ``ForecastResult``
back into the legacy ``src.models.forecast.ForecastResult`` shape (the extra
Freshness/Safety fields are dropped at this boundary, matching Phase 0
output).
"""

from __future__ import annotations

from typing import Optional

from src.core.domain.vitals import VitalSignsWindow as _CoreWindow
from src.core.forecasting.forecaster import (
    BOUNDS,
    clamp as _clamp,
    compute_uncertainty as _compute_uncertainty,
    extrapolate_value as _extrapolate_value,
    forecast_vitals as _core_forecast_vitals,
)
from src.models.forecast import ForecastResult
from src.models.vitals import VitalSignsWindow

__all__ = [
    "BOUNDS",
    "clamp",
    "_clamp",
    "extrapolate_value",
    "compute_uncertainty",
    "forecast_vitals",
    "_extrapolate_value",
    "_compute_uncertainty",
]

clamp = _clamp
extrapolate_value = _extrapolate_value
compute_uncertainty = _compute_uncertainty


def forecast_vitals(
    current_window: VitalSignsWindow,
    horizon_minutes: int,
    trend_per_hour: Optional[dict[str, float]] = None,
) -> ForecastResult:
    """Flat-line trend default, clinical clamping + growing uncertainty.

    Delegates to the Core forecaster (behavior identical to Phase 0) and
    converts the result back to the legacy ``ForecastResult`` model.
    """
    core_window = _CoreWindow(**current_window.model_dump())
    core_result = _core_forecast_vitals(core_window, horizon_minutes, trend_per_hour)
    return ForecastResult(**core_result.model_dump())
