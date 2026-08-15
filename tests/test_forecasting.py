"""Tests for forecasting logic (v2 core).

The legacy ensemble layer (src.forecasting.ensemble,
src.forecasting.backends.DeterministicBackend) has no v2 equivalent; its
behaviour is covered by the episode-based forecast/deterioration contract
tests. The ensemble-specific tests were removed here.
"""

from src.core.domain.vitals import VitalSignsWindow
from src.core.forecasting.forecaster import (
    compute_uncertainty,
    extrapolate_value,
    forecast_vitals,
)


class TestExtrapolation:
    def test_extrapolate_basic(self):
        assert extrapolate_value(100.0, 60, 5.0) == 105.0  # +5 per hour

    def test_extrapolate_no_trend(self):
        assert extrapolate_value(100.0, 60, 0.0) == 100.0

    def test_extrapolate_none(self):
        assert extrapolate_value(None, 60, 0.0) is None

    def test_uncertainty_grows_with_horizon(self):
        u1 = compute_uncertainty(60)
        u4 = compute_uncertainty(240)
        u12 = compute_uncertainty(720)
        assert u1 < u4 < u12


class TestForecastVitals:
    def test_forecast_basic(self):
        current = VitalSignsWindow(
            patient_id="PT-001",
            window_start="2026-07-02T08:00:00",
            window_end="2026-07-02T08:05:00",
            heart_rate=72,
            systolic_bp=120,
            spo2=98,
            respiratory_rate=16,
            temperature=36.5,
        )
        result = forecast_vitals(current, 60)
        assert result.patient_id == "PT-001"
        assert result.horizon_minutes == 60
        assert result.forecasted_vitals.heart_rate == 72.0
        assert result.deterioration_index == 0.0  # flat-line trend -> 0.0
        assert result.severity == "NORMAL"

    def test_forecast_with_trend(self):
        current = VitalSignsWindow(
            patient_id="PT-001",
            window_start="2026-07-02T08:00:00",
            window_end="2026-07-02T08:05:00",
            heart_rate=80,
        )
        result = forecast_vitals(current, 60, trend_per_hour={"heart_rate": 10.0})
        assert result.forecasted_vitals.heart_rate == 90.0  # 80 + 10

    def test_uncertainty_bounds(self):
        current = VitalSignsWindow(
            patient_id="PT-001",
            window_start="2026-07-02T08:00:00",
            window_end="2026-07-02T08:05:00",
            heart_rate=80,
        )
        result = forecast_vitals(current, 60)
        assert result.uncertainty_lower.heart_rate < result.forecasted_vitals.heart_rate
        assert result.uncertainty_upper.heart_rate > result.forecasted_vitals.heart_rate
