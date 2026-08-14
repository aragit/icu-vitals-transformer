"""Port protocols for forecasting backends (hexagonal 'driven' adapters).

The ``ForecastBackend`` protocol is consumed by the core forecaster and the
``SafetyShell`` decorator. Adapters live under ``src/forecasting/backends``
in the legacy module graph but the core depends only on this protocol.
"""

from typing import Protocol, runtime_checkable

from src.core.domain.forecast import ForecastResult
from src.core.domain.vitals import VitalSignsWindow


@runtime_checkable
class ForecastBackend(Protocol):
    """Projects a vital-sign window forward across a horizon.

    Implementations may be deterministic, neural, or remote; the core and
    safety shell only depend on this contract.
    """

    async def forecast(
        self,
        window: VitalSignsWindow,
        horizon_minutes: int,
        trend_per_hour: dict[str, float],
    ) -> ForecastResult:
        ...


@runtime_checkable
class SafetyBackend(Protocol):
    """Validates / sanitizes a forecast against clinical safety bounds."""

    def validate(
        self,
        result: ForecastResult,
        window: VitalSignsWindow,
    ) -> ForecastResult:
        ...
