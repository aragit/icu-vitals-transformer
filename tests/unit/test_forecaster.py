"""Unit tests for deterministic forecasting (baseline contract).

Pin ``src.core.forecasting.forecaster`` behavior: flat-line default trend,
clinical bound clamping, growing uncertainty with horizon, and null-channel
propagation. See docs/BASELINE.md §5.3.
"""

from datetime import timedelta

import pytest

from src.core.domain.vitals import VitalSignsWindow
from src.core.forecasting.forecaster import (
    BOUNDS,
    clamp,
    compute_uncertainty,
    extrapolate_value,
    forecast_vitals,
)

pytestmark = pytest.mark.unit


def _full_window(patient_id: str = "PT-001", hr=72, sbp=120, dbp=80, spo2=98, rr=16,
                 temp=36.5, avpu="A"):
    return VitalSignsWindow(
        patient_id=patient_id,
        window_start="2026-07-02T08:00:00",
        window_end="2026-07-02T08:05:00",
        heart_rate=hr,
        systolic_bp=sbp,
        diastolic_bp=dbp,
        spo2=spo2,
        respiratory_rate=rr,
        temperature=temp,
        avpu=avpu,
    )


class TestExtrapolateValue:
    def test_no_trend_is_flat(self):
        assert extrapolate_value(100.0, 60, 0.0) == 100.0
        assert extrapolate_value(100.0, 720, 0.0) == 100.0

    def test_trend_applied_per_hour(self):
        # 1h horizon, +5/hr -> +5
        assert extrapolate_value(100.0, 60, 5.0) == 105.0
        # 12h horizon, +5/hr -> +60
        assert extrapolate_value(100.0, 720, 5.0) == 160.0

    def test_negative_trend(self):
        assert extrapolate_value(100.0, 60, -10.0) == 90.0

    def test_none_pass_through(self):
        assert extrapolate_value(None, 60, 5.0) is None


class TestUncertainty:
    def test_uncertainty_grows_with_horizon(self):
        u1 = compute_uncertainty(60)
        u4 = compute_uncertainty(240)
        u12 = compute_uncertainty(720)
        assert u1 < u4 < u12

    def test_uncertainty_values(self):
        # baseline: 2.0 * (1 + 0.1 * h/60)
        assert compute_uncertainty(60) == 2.2
        assert compute_uncertainty(240) == 2.8
        assert compute_uncertainty(720) == 4.4

    def test_bounds_spread_grows_with_horizon(self):
        current = _full_window()
        r1 = forecast_vitals(current, 60)
        r4 = forecast_vitals(current, 240)
        r12 = forecast_vitals(current, 720)
        def spread(r):
            return r.uncertainty_upper.heart_rate - r.uncertainty_lower.heart_rate
        assert spread(r1) < spread(r4) < spread(r12)
        # spread == 2 * uncertainty (within floating point tolerance).
        assert spread(r1) == pytest.approx(round(2 * compute_uncertainty(60), 2))

    def test_bounds_bracket_forecast(self):
        current = _full_window()
        result = forecast_vitals(current, 60)
        assert result.uncertainty_lower.heart_rate < result.forecasted_vitals.heart_rate
        assert result.uncertainty_upper.heart_rate > result.forecasted_vitals.heart_rate


class TestClamp:
    def test_clamp_within_bounds(self):
        assert clamp("heart_rate", 150.0) == 150.0
        assert clamp("spo2", 95.0) == 95.0

    def test_clamp_upper_bound(self):
        assert clamp("heart_rate", 500.0) == BOUNDS["heart_rate"][1]
        assert clamp("temperature", 99.0) == BOUNDS["temperature"][1]

    def test_clamp_lower_bound(self):
        assert clamp("heart_rate", -10.0) == BOUNDS["heart_rate"][0]
        assert clamp("spo2", -5.0) == BOUNDS["spo2"][0]

    def test_clamp_none(self):
        assert clamp("heart_rate", None) is None

    def test_clamp_unknown_field_uses_default_bounds(self):
        # Unknown field falls back to (0, 999).
        assert clamp("unknown", 5000.0) == 999.0


class TestForecastVitals:
    def test_flat_line_projection(self):
        current = _full_window()
        result = forecast_vitals(current, 60, trend_per_hour={})
        # No trend -> forecasted equals current (within clamping).
        assert result.forecasted_vitals.heart_rate == 72.0
        assert result.forecasted_vitals.systolic_bp == 120.0
        assert result.forecasted_vitals.spo2 == 98.0
        assert result.forecasted_vitals.respiratory_rate == 16.0
        assert result.forecasted_vitals.temperature == 36.5
        assert result.forecasted_vitals.avpu == "A"

    def test_default_trend_is_zero(self):
        # Omitting trend_per_hour defaults every trend to 0.0 -> flat-line.
        current = _full_window()
        result = forecast_vitals(current, 240)
        assert result.forecasted_vitals.heart_rate == current.heart_rate

    def test_horizon_minutes_recorded(self):
        result = forecast_vitals(_full_window(), 240)
        assert result.horizon_minutes == 240
        # forecasted window spans horizon_minutes from the current window_end.
        assert result.forecasted_vitals.window_end == (
            result.forecasted_vitals.window_start + timedelta(minutes=240)
        )

    def test_clamping_upper_bound(self):
        # Huge positive trend must clamp to clinical upper bound.
        current = _full_window(hr=200)
        result = forecast_vitals(
            current, 60, trend_per_hour={"heart_rate": 3000.0, "temperature": 2000.0}
        )
        assert result.forecasted_vitals.heart_rate == BOUNDS["heart_rate"][1]
        assert result.forecasted_vitals.temperature == BOUNDS["temperature"][1]

    def test_clamping_lower_bound(self):
        current = _full_window(spo2=50)
        result = forecast_vitals(current, 60, trend_per_hour={"spo2": -5000.0})
        assert result.forecasted_vitals.spo2 == BOUNDS["spo2"][0]

    def test_uncertainty_bounds_also_clamped(self):
        current = _full_window(temp=37)
        result = forecast_vitals(current, 60, trend_per_hour={"temperature": 100000.0})
        assert result.uncertainty_upper.temperature == BOUNDS["temperature"][1]

    def test_null_channel_stays_null(self):
        current = _full_window(hr=80, sbp=120, dbp=80, spo2=98, rr=16, temp=36.5)
        # Wipe one channel.
        current.heart_rate = None
        result = forecast_vitals(current, 60)
        assert result.forecasted_vitals.heart_rate is None
        assert result.uncertainty_lower.heart_rate is None
        assert result.uncertainty_upper.heart_rate is None

    def test_none_channels_forecast_none(self):
        current = VitalSignsWindow(
            patient_id="PT-001",
            window_start="2026-07-02T08:00:00",
            window_end="2026-07-02T08:05:00",
        )
        result = forecast_vitals(current, 60)
        assert result.forecasted_vitals.heart_rate is None
        assert result.forecasted_vitals.systolic_bp is None
        assert result.forecasted_vitals.spo2 is None
        # uncertainty_lower/upper are always VitalSignsWindow objects; their
        # None channels stay None.
        assert result.uncertainty_lower is not None
        assert result.uncertainty_lower.heart_rate is None

    def test_truthy_zero_value_edge(self):
        # Legacy note: bounds use `if current.X else None`; a falsy 0.0 value
        # therefore yields None bounds. Lock that behavior here.
        current = _full_window(hr=0)
        result = forecast_vitals(current, 60)
        # forecasted uses extrapolate (handles 0.0), but bounds use the
        # truthiness guard so heart_rate bounds are None.
        assert result.uncertainty_lower.heart_rate is None
        assert result.uncertainty_upper.heart_rate is None
