"""Pluggable forecast backends.

Defines the ForecastBackend protocol and the default DeterministicBackend.
Any backend implementing this protocol can be injected into ensemble_forecast(),
enabling alternative forecasting strategies (neural, API-based, etc.) without
modifying the ensemble or governance layers.
"""

from typing import Protocol

from src.models.vitals import VitalSignsWindow
from src.models.forecast import ForecastResult
from src.forecasting.forecaster import forecast_vitals


class ForecastBackend(Protocol):
    """Protocol for forecast backends.

    Implementations must produce a ForecastResult with forecasted vitals,
    uncertainty bounds, and placeholder governance fields (deterioration_index,
    severity) that the ensemble layer overwrites.
    """

    def forecast(
        self,
        current_window: VitalSignsWindow,
        horizon_minutes: int,
        trend_per_hour: dict[str, float] | None = None,
    ) -> ForecastResult:
        """Generate a forecast for the given window and horizon."""


class DeterministicBackend:
    """Default backend using linear trend extrapolation with clinical bounds."""

    def forecast(
        self,
        current_window: VitalSignsWindow,
        horizon_minutes: int,
        trend_per_hour: dict[str, float] | None = None,
    ) -> ForecastResult:
        return forecast_vitals(current_window, horizon_minutes, trend_per_hour)
