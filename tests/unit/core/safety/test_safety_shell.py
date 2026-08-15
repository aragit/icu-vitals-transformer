"""Unit tests for the core SafetyShell forecast validator.

Validates the baseline contract (docs/BASELINE.md):
  - physiological bound clamping
  - lower <= forecasted <= upper per-channel enforcement
  - stale-data warning injection past the 300s freshness threshold
  - fail-closed flat-line fallback when the inner backend raises
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from src.core.domain.forecast import ForecastResult
from src.core.domain.vitals import VitalSignsWindow
from src.core.forecasting.forecaster import BOUNDS
from src.core.safety.shell import STALE_DATA_THRESHOLD_SECONDS, SafetyShell
from src.ports.forecaster import ForecastBackend

pytestmark = pytest.mark.unit


def _window(**overrides: object) -> VitalSignsWindow:
    now = datetime.now(timezone.utc)
    base: dict[str, object] = {
        "patient_id": "PT-001",
        "window_start": now - timedelta(minutes=5),
        "window_end": now,
        "heart_rate": 72.0,
        "systolic_bp": 120.0,
        "diastolic_bp": 80.0,
        "spo2": 98.0,
        "respiratory_rate": 16.0,
        "temperature": 36.5,
        "avpu": "A",
    }
    base.update(overrides)
    return VitalSignsWindow(**base)  # type: ignore[arg-type]


def _result(
    forecasted: VitalSignsWindow,
    lower: VitalSignsWindow,
    upper: VitalSignsWindow,
    freshness: int = 0,
    stale: bool = False,
    factors: list[str] | None = None,
) -> ForecastResult:
    return ForecastResult(
        patient_id=forecasted.patient_id,
        horizon_minutes=60,
        forecasted_vitals=forecasted,
        uncertainty_lower=lower,
        uncertainty_upper=upper,
        deterioration_index=0.0,
        severity="NORMAL",
        data_freshness_seconds=freshness,
        stale_data_warning=stale,
        contributing_factors=factors or [],
    )


class FailingBackend(ForecastBackend):
    async def forecast(
        self,
        window: VitalSignsWindow,
        horizon_minutes: int,
        trend_per_hour: dict[str, float],
    ) -> ForecastResult:
        raise RuntimeError("backend exploded")


class _NoopBackend(ForecastBackend):
    def __init__(self, result: ForecastResult) -> None:
        self._result = result

    async def forecast(
        self,
        window: VitalSignsWindow,
        horizon_minutes: int,
        trend_per_hour: dict[str, float],
    ) -> ForecastResult:
        return self._result


class TestSafetyShellClamping:
    def test_physiological_bound_clamping(self) -> None:
        # heart_rate cap is 300; inject 999 via model_construct (bypasses Field).
        raw = _window()
        forecasted = VitalSignsWindow.model_construct(
            **{**raw.model_dump(), "heart_rate": 999.0}
        )
        shell = SafetyShell(_NoopBackend(_result(forecasted, forecasted, forecasted)))
        result = shell.validate(
            _result(forecasted, forecasted, forecasted), raw
        )
        assert result.forecasted_vitals.heart_rate == BOUNDS["heart_rate"][1]


class TestBoundOrdering:
    def test_upper_lower_reanchored_to_forecast(self) -> None:
        base = _window()
        # upper < forecasted on heart_rate -> should be raised to forecasted.
        lower = _window()
        upper = VitalSignsWindow.model_construct(
            **{**base.model_dump(), "heart_rate": 10.0}
        )
        shell = SafetyShell(_NoopBackend(_result(base, lower, upper)))
        result = shell.validate(_result(base, lower, upper), base)
        assert result.uncertainty_upper.heart_rate == result.forecasted_vitals.heart_rate


class TestStaleDataGuard:
    def test_stale_data_warning_injected(self) -> None:
        base = _window()
        result = _result(base, base, base, freshness=STALE_DATA_THRESHOLD_SECONDS + 1)
        shell = SafetyShell(_NoopBackend(result))
        out = shell.validate(result, base)
        assert out.stale_data_warning is True
        assert "stale_data_warning" in out.contributing_factors

    def test_fresh_data_not_flagged(self) -> None:
        base = _window()
        result = _result(base, base, base, freshness=60, stale=False)
        shell = SafetyShell(_NoopBackend(result))
        out = shell.validate(result, base)
        assert out.stale_data_warning is False
        assert "stale_data_warning" not in out.contributing_factors


class TestFailClosed:
    async def test_flatline_fallback_on_inner_failure(self) -> None:
        window = _window()
        shell = SafetyShell(FailingBackend())
        result = await shell.forecast(window, 60, {})
        # Flat-line (zero trend) -> forecasted equals the current window values.
        assert result.forecasted_vitals.heart_rate == window.heart_rate
        assert result.forecasted_vitals.systolic_bp == window.systolic_bp
        assert result.patient_id == window.patient_id


class TestInputImmutability:
    """Tasks 2.3 + 4.1: validate() must not mutate the caller's ForecastResult,
    and the core domain model must accept out-of-bound projections (no Field
    bounds) so SafetyShell can clamp them instead of raising ValidationError."""

    def test_validate_does_not_mutate_input(self) -> None:
        forecasted = _window(heart_rate=350.0)
        # 4.1: out-of-bound projection constructs without error.
        assert forecasted.heart_rate == 350.0
        lower = _window(heart_rate=350.0)
        upper = _window(heart_rate=350.0)
        result = _result(forecasted, lower, upper)

        shell = SafetyShell(_NoopBackend(result))
        out = shell.validate(result, forecasted)

        # Input ForecastResult is left untouched.
        assert result.forecasted_vitals.heart_rate == 350.0
        assert result.uncertainty_lower.heart_rate == 350.0
        assert result.uncertainty_upper.heart_rate == 350.0
        assert "stale_data_warning" not in result.contributing_factors
        # Output is clamped to the physiological cap (heart_rate upper = 300).
        assert out.forecasted_vitals.heart_rate == 300.0

    def test_validate_clamps_and_reanchors_bounds(self) -> None:
        # upper below forecasted on heart_rate -> raised to forecasted on output;
        # input upper unchanged.
        forecasted = _window(heart_rate=120.0)
        upper = _window(heart_rate=10.0)
        lower = _window()
        result = _result(forecasted, lower, upper)
        shell = SafetyShell(_NoopBackend(result))
        out = shell.validate(result, forecasted)
        assert out.uncertainty_upper.heart_rate == 120.0
        assert result.uncertainty_upper.heart_rate == 10.0  # input unchanged


class TestStaleDataCallback:
    """Phase A.3: on_stale_data callback fires on stale results, not fresh."""

    def test_stale_result_invokes_callback_once(self) -> None:
        base = _window()
        result = _result(base, base, base, freshness=STALE_DATA_THRESHOLD_SECONDS + 1)
        callback = MagicMock()
        shell = SafetyShell(_NoopBackend(result), on_stale_data=callback)
        shell.validate(result, base)
        callback.assert_called_once()

    def test_fresh_result_does_not_invoke_callback(self) -> None:
        base = _window()
        result = _result(base, base, base, freshness=60, stale=False)
        callback = MagicMock()
        shell = SafetyShell(_NoopBackend(result), on_stale_data=callback)
        shell.validate(result, base)
        callback.assert_not_called()

    def test_callback_not_inherited_from_outer_scope(self) -> None:
        """No on_stale_data callback => stale flag still set, no crash."""
        base = _window()
        result = _result(base, base, base, freshness=STALE_DATA_THRESHOLD_SECONDS + 1)
        shell = SafetyShell(_NoopBackend(result))
        out = shell.validate(result, base)
        assert out.stale_data_warning is True
