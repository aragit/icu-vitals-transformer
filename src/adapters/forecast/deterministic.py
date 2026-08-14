"""Async deterministic forecast backend adapter.

Implements the Core ``ForecastBackend`` protocol by delegating to the pure
Core deterministic forecaster (``src.core.forecasting.forecaster.forecast_vitals``)
and adapting the synchronous call into the async contract expected by the
``ClinicalAssessmentService`` / ``SafetyShell``.

Adapters depend inward on ``src.core.*`` + ``src.ports.*`` only (hexagonal
inversion) and may import FastAPI/MCP here at the adapter boundary, but this
particular backend is framework-agnostic.
"""

from __future__ import annotations

import asyncio

from src.core.domain.forecast import ForecastResult
from src.core.domain.vitals import VitalSignsWindow
from src.core.forecasting.forecaster import forecast_vitals
from src.ports.forecaster import ForecastBackend


class DeterministicForecastBackend(ForecastBackend):
    """Async adapter wrapping the Core deterministic forecaster.

    The Core ``forecast_vitals`` is synchronous and CPU-bound for small
    horizons; we yield control to the event loop with ``asyncio.to_thread``
    so concurrent forecasts don't block the loop.
    """

    async def forecast(
        self,
        window: VitalSignsWindow,
        horizon_minutes: int,
        trend_per_hour: dict[str, float],
    ) -> ForecastResult:
        return await asyncio.to_thread(
            forecast_vitals,
            window,
            horizon_minutes,
            trend_per_hour,
        )


__all__ = ["DeterministicForecastBackend"]
