"""Tests for forecasting and ensemble logic."""

import pytest

from src.forecasting.forecaster import _extrapolate_value, _compute_uncertainty, forecast_vitals
from src.forecasting.ensemble import ensemble_forecast, ensemble_deterioration_index, HORIZON_WEIGHTS
from src.models.vitals import VitalSignsWindow


class TestExtrapolation:
    def test_extrapolate_basic(self):
        assert _extrapolate_value(100.0, 60, 5.0) == 105.0  # +5 per hour

    def test_extrapolate_no_trend(self):
        assert _extrapolate_value(100.0, 60, 0.0) == 100.0

    def test_extrapolate_none(self):
        assert _extrapolate_value(None, 60, 0.0) is None

    def test_uncertainty_grows_with_horizon(self):
        u1 = _compute_uncertainty(60)
        u4 = _compute_uncertainty(240)
        u12 = _compute_uncertainty(720)
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
        assert result.deterioration_index == 0.0  # set by ensemble
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


class TestEnsembleForecast:
    def test_three_horizons(self):
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
        results = ensemble_forecast(current)
        assert len(results) == 3
        assert results[0].horizon_minutes == 60
        assert results[1].horizon_minutes == 240
        assert results[2].horizon_minutes == 720
        # All should have governance classification now
        assert results[0].severity == "NORMAL"

    def test_deteriorating_patient(self):
        current = VitalSignsWindow(
            patient_id="PT-001",
            window_start="2026-07-02T08:00:00",
            window_end="2026-07-02T08:05:00",
            heart_rate=130,
            systolic_bp=85,
            spo2=90,
            respiratory_rate=26,
            temperature=39.5,
        )
        results = ensemble_forecast(current)
        # At least one horizon should trigger ALERT or EMERGENCY
        severities = [r.severity for r in results]
        assert any(s in ("ALERT", "EMERGENCY") for s in severities)


class TestEnsembleDeteriorationIndex:
    def test_empty_raises(self):
        with pytest.raises(ValueError):
            ensemble_deterioration_index([])

    def test_normal_patient(self):
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
        forecasts = ensemble_forecast(current)
        assessment = ensemble_deterioration_index(forecasts)
        assert assessment.patient_id == "PT-001"
        assert assessment.severity == "NORMAL"
        assert assessment.ensemble_score >= 0

    def test_weights_sum_to_one(self):
        assert sum(HORIZON_WEIGHTS.values()) == 1.0
