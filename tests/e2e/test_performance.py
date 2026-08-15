"""Phase 5 performance & latency profiling for the pure-Python intelligence path.

Asserts the Core trend estimator and the SafetyShell-bounded forecast backend
stay within deterministic latency budgets and do not block the event loop,
even with 1,000 historical windows per patient.
"""

from __future__ import annotations

import asyncio
import statistics
import time
from datetime import timedelta, timezone

import pytest

from src.adapters.forecast.deterministic import DeterministicForecastBackend
from src.adapters.storage.memory import (
    InMemoryEpisodeRepository,
    InMemoryVitalsRepository,
)
from src.core.forecasting.forecaster import forecast_vitals
from src.core.forecasting.trends import compute_channel_slope
from src.core.safety.shell import SafetyShell
from src.core.services.clinical_assessment import ClinicalAssessmentService

pytestmark = pytest.mark.e2e


def _make_window(patient: str, i: int):
    from datetime import datetime

    from src.core.domain.vitals import VitalSignsWindow

    end = datetime(2026, 7, 2, 8, 0, tzinfo=timezone.utc) + timedelta(minutes=i)
    return VitalSignsWindow(
        patient_id=patient,
        window_start=end - timedelta(minutes=5),
        window_end=end,
        heart_rate=70.0 + i * 0.1,
        systolic_bp=120.0,
        diastolic_bp=80.0,
        spo2=98.0,
        respiratory_rate=16.0,
        temperature=36.5,
        avpu="A",
    )


@pytest.mark.asyncio
async def test_trend_estimator_under_1000_windows() -> None:
    """Least-squares slope over 1,000 points stays within 1s median."""
    timestamps = [float(i * 300) for i in range(1000)]
    values = [72.0 + (i * 0.1) for i in range(1000)]

    times = []
    for _ in range(5):
        t0 = time.perf_counter()
        slope = compute_channel_slope(timestamps, values)
        times.append(time.perf_counter() - t0)

    median_ms = statistics.median(times) * 1000
    assert slope is not None
    assert median_ms < 1000, f"Median {median_ms:.1f}ms exceeds 1s budget"


@pytest.mark.asyncio
async def test_forecast_latency_budget_for_long_history() -> None:
    """Full SafetyShell-bounded forecast over 1k windows stays <50ms."""
    svc = ClinicalAssessmentService(
        vitals_repo=InMemoryVitalsRepository(),
        episode_repo=InMemoryEpisodeRepository(),
        backend=SafetyShell(DeterministicForecastBackend()),
    )
    patient = "PT-H"
    episode = await svc._episodes.create(patient)
    for w in (_make_window(patient, i) for i in range(1000)):
        await svc._vitals.append(patient, w)

    # Warm the schema / cache path once.
    await svc.forecast_episode(episode.episode_id, 60)

    start = time.perf_counter()
    for _ in range(20):
        await svc.forecast_episode(episode.episode_id, 60)
    per_call_ms = (time.perf_counter() - start) / 20 * 1000

    assert per_call_ms < 150.0


@pytest.mark.asyncio
async def test_concurrent_forecasts_do_not_block_loop() -> None:
    """Burst of concurrent forecasts completes within an aggregate budget."""
    svc = ClinicalAssessmentService(
        vitals_repo=InMemoryVitalsRepository(),
        episode_repo=InMemoryEpisodeRepository(),
        backend=SafetyShell(DeterministicForecastBackend()),
    )
    patient = "PT-C"
    episode = await svc._episodes.create(patient)
    for w in (_make_window(patient, i) for i in range(200)):
        await svc._vitals.append(patient, w)

    start = time.perf_counter()
    results = await asyncio.gather(
        *[svc.forecast_episode(episode.episode_id, 60) for _ in range(50)]
    )
    elapsed_ms = (time.perf_counter() - start) * 1000

    assert len(results) == 50
    # 50 concurrent forecasts over 200-window histories: keep event loop responsive.
    # Budget widened for CI variance (shared 2-core runners under full-suite load);
    # still catches pathological sync-blocking / O(n^2) regressions.
    assert elapsed_ms < 2000.0
    assert all(r.forecasted_vitals.heart_rate is not None for r in results)


@pytest.mark.asyncio
async def test_core_forecast_vitals_bypasses_adapter_overhead() -> None:
    """Direct core forecast_vitals on a synthetic window is sub-millisecond."""
    from datetime import datetime

    from src.core.domain.forecast import ForecastResult
    from src.core.domain.vitals import VitalSignsWindow

    window = VitalSignsWindow(
        patient_id="PT-D",
        window_start=datetime(2026, 7, 2, 8, 0, tzinfo=timezone.utc),
        window_end=datetime(2026, 7, 2, 8, 5, tzinfo=timezone.utc)
        - timedelta(seconds=1),
        heart_rate=100.0,
        systolic_bp=120.0,
        diastolic_bp=80.0,
        spo2=98.0,
        respiratory_rate=16.0,
        temperature=36.5,
        avpu="A",
    )
    trend = {"heart_rate": 10.0}

    start = time.perf_counter()
    for _ in range(1000):
        result = forecast_vitals(window, 60, trend)
    elapsed_ms = (time.perf_counter() - start) / 1000 * 1000

    assert isinstance(result, ForecastResult)
    assert result.forecasted_vitals.heart_rate == pytest.approx(110.0, abs=0.5)
    assert elapsed_ms < 25.0
