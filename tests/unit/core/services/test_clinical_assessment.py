"""Unit tests for the ClinicalAssessmentService end-to-end lifecycle."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.adapters.forecast.deterministic import DeterministicForecastBackend
from src.adapters.storage.memory import (
    InMemoryAssessmentRepository,
    InMemoryEpisodeRepository,
    InMemoryVitalsRepository,
)
from src.core.domain.episode import EpisodeState
from src.core.domain.vitals import VitalSignsWindow
from src.core.safety.shell import SafetyShell
from src.core.services.clinical_assessment import ClinicalAssessmentService

pytestmark = pytest.mark.unit


def _ts(minutes: int) -> datetime:
    return datetime(2026, 7, 2, 8, minutes, 0, tzinfo=timezone.utc)


def _window(patient_id: str, end_minute: int, hr: float | None = 72.0) -> VitalSignsWindow:
    end = _ts(end_minute)
    return VitalSignsWindow(
        patient_id=patient_id,
        window_start=end - timedelta(minutes=5),
        window_end=end,
        heart_rate=hr,
        systolic_bp=120.0,
        diastolic_bp=80.0,
        spo2=98.0,
        respiratory_rate=16.0,
        temperature=36.5,
        avpu="A",
    )


def _service() -> ClinicalAssessmentService:
    return ClinicalAssessmentService(
        vitals_repo=InMemoryVitalsRepository(),
        episode_repo=InMemoryEpisodeRepository(),
        backend=SafetyShell(DeterministicForecastBackend()),
        assessment_repo=InMemoryAssessmentRepository(),
    )


class TestIngestAndWindow:
    async def test_auto_creates_active_episode(self) -> None:
        svc = _service()
        observations = [
            {
                "resourceType": "Observation",
                "subject": {"reference": "Patient/PT-001"},
                "code": {"coding": [{"system": "http://loinc.org", "code": "8867-4"}]},
                "valueQuantity": {"value": 72.0, "unit": "beats/min"},
                "effectiveDateTime": "2026-07-02T08:05:00",
            }
        ]
        window = await svc.ingest_and_window("PT-001", observations)
        assert window.heart_rate == 72.0
        episode = await svc._episodes.get_active_by_patient("PT-001")
        assert episode is not None
        assert episode.state == EpisodeState.NORMAL
        assert episode.patient_id == "PT-001"


class TestAssessEpisode:
    async def test_lifecycle_normal(self) -> None:
        svc = _service()
        # Single recent window -> flat-line forecast -> DDS 0 -> NORMAL.
        await svc._vitals.append("PT-001", _window("PT-001", 5, hr=72.0))
        episode = await svc._episodes.create("PT-001")

        assessment = await svc.assess_episode(episode.episode_id, 60)
        assert assessment.ensemble_score == 0.0
        assert assessment.severity == "NORMAL"

        transitioned = await svc._episodes.get(episode.episode_id)
        assert transitioned is not None
        assert transitioned.state == EpisodeState.NORMAL

        trail = await svc._assessments.get_audit_trail(episode.episode_id)
        assert trail and trail[-1].severity == "NORMAL"

    async def test_trend_elevates_score(self) -> None:
        svc = _service()
        # Two windows 5 min apart with rising HR -> slope 120/hr -> forecasted
        # HR at +60min = 82 + 120 = 202 -> heart_rate critical (+3) -> WARNING.
        w1 = _window("PT-001", 0, hr=72.0)
        w2 = _window("PT-001", 5, hr=82.0)
        await svc._vitals.append("PT-001", w1)
        await svc._vitals.append("PT-001", w2)
        episode = await svc._episodes.create("PT-001")

        assessment = await svc.assess_episode(episode.episode_id, 60)
        assert assessment.ensemble_score == 3.0
        assert assessment.severity == "WARNING"
        assert "heart_rate_critical" in assessment.contributing_factors

        transitioned = await svc._episodes.get(episode.episode_id)
        assert transitioned is not None
        assert transitioned.state == EpisodeState.WARNING
