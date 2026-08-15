"""Unit tests for the ClinicalAssessmentService end-to-end lifecycle."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

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
        assert assessment.dds_score == 0.0
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
        assert assessment.dds_score == 3.0
        assert assessment.severity == "WARNING"
        assert "heart_rate_critical" in assessment.contributing_factors

        transitioned = await svc._episodes.get(episode.episode_id)
        assert transitioned is not None
        assert transitioned.state == EpisodeState.WARNING


class TestDiscoverChannels:
    """Task 2.1 acceptance #3: discover_channels() reflects the observed window,
    including AVPU sourced from a valueCodeableConcept observation."""

    def _obs(self, loinc: str, qty=None, codeable=None) -> dict:
        obj = {
            "resourceType": "Observation",
            "subject": {"reference": "Patient/PT-001"},
            "code": {"coding": [{"system": "http://loinc.org", "code": loinc}]},
            "effectiveDateTime": "2026-07-02T08:05:00Z",
        }
        if qty is not None:
            obj["valueQuantity"] = {"value": qty[0], "unit": qty[1]}
        if codeable is not None:
            obj["valueCodeableConcept"] = {"coding": [codeable]}
        return obj

    async def test_discover_channels_mixed_obs(self) -> None:
        svc = _service()
        observations = [
            self._obs("8867-4", qty=(72.0, "bpm")),
            # SNOMED 450847001 = Responds to pain -> "P"
            self._obs("8867-4", codeable={"system": "http://snomed.info/sct", "code": "450847001"}),
            self._obs("2708-6", qty=(98.0, "%")),
        ]
        await svc.ingest_and_window("PT-001", observations)
        episode = await svc._episodes.get_active_by_patient("PT-001")
        assert episode is not None
        channels = await svc.discover_channels(episode.episode_id)
        assert "heart_rate" in channels
        assert "spo2" in channels
        assert "avpu" in channels
        assert "systolic_bp" not in channels


class TestMetricsInstrumentation:
    """Phase A.2: INGEST_DURATION and FORECAST_DURATION histograms are observed."""

    def _hr_obs(self, patient_id: str = "PT-001", hr: float = 72.0) -> dict:
        return {
            "resourceType": "Observation",
            "subject": {"reference": f"Patient/{patient_id}"},
            "code": {"coding": [{"system": "http://loinc.org", "code": "8867-4"}]},
            "valueQuantity": {"value": hr, "unit": "bpm"},
            "effectiveDateTime": "2026-07-02T08:05:00",
        }

    def _mock_hist(self) -> MagicMock:
        mock_hist = MagicMock()
        mock_cm = MagicMock()
        mock_hist.time.return_value = mock_cm
        return mock_hist

    async def test_ingest_instruments_ingest_duration(self) -> None:
        svc = _service()
        mock_hist = self._mock_hist()
        with patch(
            "src.core.services.clinical_assessment.INGEST_DURATION", mock_hist
        ):
            await svc.ingest_and_window("PT-001", [self._hr_obs()])
        mock_hist.time.assert_called_once()

    async def test_forecast_instruments_forecast_duration(self) -> None:
        svc = _service()
        await svc.ingest_and_window("PT-001", [self._hr_obs()])
        episode = await svc._episodes.get_active_by_patient("PT-001")
        assert episode is not None

        mock_hist = self._mock_hist()
        with patch(
            "src.core.services.clinical_assessment.FORECAST_DURATION", mock_hist
        ):
            await svc.forecast_episode(episode.episode_id, 60)
        mock_hist.time.assert_called_once()
