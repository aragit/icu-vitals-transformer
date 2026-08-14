"""Phase 3 integration tests for the intelligence layer.

Verifies the end-to-end path: ``VitalsRepository.get_history`` -> pure-Python
``trends.compute_channel_slope`` -> ``DeterministicForecastBackend`` ->
``SafetyShell`` clamping/bounds, producing dynamic linear extrapolation with
clinical bound enforcement. All assertions are pure-Python (no numpy).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.adapters.forecast.deterministic import DeterministicForecastBackend
from src.adapters.storage.memory import (
    InMemoryAssessmentRepository,
    InMemoryEpisodeRepository,
    InMemoryVitalsRepository,
)
from src.core.domain.vitals import VitalSignsWindow
from src.core.safety.shell import SafetyShell
from src.core.services.clinical_assessment import ClinicalAssessmentService

pytestmark = pytest.mark.unit


def _ts(minutes: int) -> datetime:
    return datetime(2026, 7, 2, 8, 0, 0, tzinfo=timezone.utc) + timedelta(minutes=minutes)


def _window(
    patient_id: str,
    end_minute: int,
    hr: float | None = 72.0,
    spo2: float | None = 98.0,
    temp: float | None = 36.5,
    sbp: float | None = 120.0,
    dbp: float | None = 80.0,
    rr: float | None = 16.0,
    avpu: str | None = "A",
) -> VitalSignsWindow:
    end = _ts(end_minute)
    return VitalSignsWindow(
        patient_id=patient_id,
        window_start=end - timedelta(minutes=5),
        window_end=end,
        heart_rate=hr,
        systolic_bp=sbp,
        diastolic_bp=dbp,
        spo2=spo2,
        respiratory_rate=rr,
        temperature=temp,
        avpu=avpu,
    )


def _service() -> ClinicalAssessmentService:
    return ClinicalAssessmentService(
        vitals_repo=InMemoryVitalsRepository(),
        episode_repo=InMemoryEpisodeRepository(),
        backend=SafetyShell(DeterministicForecastBackend()),
        assessment_repo=InMemoryAssessmentRepository(),
    )


class TestMultiWindowTrend:
    """Rising HR (80->90->100 over 2h) extrapolates +10/hr -> 110 @+60m."""

    async def test_linear_extrapolation_matches_slope(self) -> None:
        svc = _service()
        for end, hr in [(0, 80.0), (60, 90.0), (120, 100.0)]:
            await svc._vitals.append("PT-T1", _window("PT-T1", end, hr=hr))
        episode = await svc._episodes.create("PT-T1")

        forecast = await svc.forecast_episode(episode.episode_id, 60)

        assert forecast.forecasted_vitals.heart_rate == pytest.approx(110.0, abs=0.5)
        assert "heart_rate_trend" in forecast.contributing_factors


class TestSparseChannels:
    """SpO2 with history computes a trend; Temperature with 1 point stays flat."""

    async def test_temperature_defaults_to_flat_line(self) -> None:
        svc = _service()
        await svc._vitals.append(
            "PT-T2", _window("PT-T2", 0, hr=80.0, spo2=95.0, temp=None)
        )
        await svc._vitals.append(
            "PT-T2", _window("PT-T2", 60, hr=80.0, spo2=96.0, temp=None)
        )
        await svc._vitals.append(
            "PT-T2", _window("PT-T2", 120, hr=80.0, spo2=97.0, temp=None)
        )
        await svc._vitals.append(
            "PT-T2", _window("PT-T2", 180, hr=80.0, spo2=94.0, temp=37.2)
        )
        episode = await svc._episodes.create("PT-T2")

        forecast = await svc.forecast_episode(episode.episode_id, 60)

        assert "spo2_trend" in forecast.contributing_factors
        assert "temperature_trend" not in forecast.contributing_factors
        assert forecast.forecasted_vitals.temperature == pytest.approx(37.2, abs=0.01)


class TestDataFreshness:
    """A window older than 300s raises the stale-data warning."""

    async def test_stale_window_flags_warning(self) -> None:
        svc = _service()
        stale_end = datetime.now(timezone.utc) - timedelta(seconds=400)
        window = VitalSignsWindow(
            patient_id="PT-T3",
            window_start=stale_end - timedelta(minutes=5),
            window_end=stale_end,
            heart_rate=72.0,
            systolic_bp=120.0,
            diastolic_bp=80.0,
            spo2=98.0,
            respiratory_rate=16.0,
            temperature=36.5,
            avpu="A",
        )
        await svc._vitals.append("PT-T3", window)
        episode = await svc._episodes.create("PT-T3")

        forecast = await svc.forecast_episode(episode.episode_id, 60)

        assert forecast.stale_data_warning is True
        assert "stale_data_warning" in forecast.contributing_factors


class TestSafetyShellClamping:
    """A trend that would extrapolate past the physiological ceiling is clamped."""

    async def test_high_heart_rate_trend_clamped_to_ceiling(self) -> None:
        svc = _service()
        # 150 -> 180 -> 210 over 5-minute gaps => 360 beats/hr slope.
        for end, hr in [(0, 150.0), (5, 180.0), (10, 210.0)]:
            await svc._vitals.append("PT-T4", _window("PT-T4", end, hr=hr))
        episode = await svc._episodes.create("PT-T4")

        forecast = await svc.forecast_episode(episode.episode_id, 60)

        # 210 + 360 = 570 -> clamped to heart_rate ceiling of 300.
        assert forecast.forecasted_vitals.heart_rate == pytest.approx(300.0, abs=0.01)
        assert forecast.forecasted_vitals.heart_rate <= 300.0
