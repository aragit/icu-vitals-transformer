"""Clinical assessment orchestrator (Core services).

Core Isolation invariant: pure Python + pydantic only. Depends only on the
core domain, core engines, and the port protocols — never on fastapi/mcp/
prometheus/redis/numpy.

Wires together the in-memory ``VitalsRepository`` (or any implementation),
``EpisodeRepository``, and a ``ForecastBackend`` (expected to be wrapped in a
``SafetyShell``) to run full ingestion -> windowing -> trend -> forecast ->
DDS assessment cycles.
"""

from __future__ import annotations

import logging
from typing import Any

from src.core.domain.episode import Episode
from src.core.domain.forecast import DeteriorationAssessment, ForecastResult
from src.core.domain.vitals import VitalSignsWindow
from src.core.forecasting.forecaster import NUMERIC_FIELDS
from src.core.forecasting.trends import compute_channel_slope
from src.core.governance.deterioration import compute_dds
from src.core.governance.severity import severity_from_score
from src.core.ingestion.fhir_parser import parse_batch
from src.core.windowing.engine import window_vitals
from src.observability.metrics import FORECAST_DURATION, INGEST_DURATION
from src.ports.forecaster import ForecastBackend
from src.ports.repository import (
    AssessmentRepository,
    EpisodeRepository,
    VitalsRepository,
)

logger = logging.getLogger(__name__)


class ClinicalAssessmentService:
    """Orchestrates the end-to-end clinical assessment workflow."""

    def __init__(
        self,
        vitals_repo: VitalsRepository,
        episode_repo: EpisodeRepository,
        backend: ForecastBackend,
        assessment_repo: AssessmentRepository | None = None,
    ) -> None:
        self._vitals = vitals_repo
        self._episodes = episode_repo
        self._backend = backend
        self._assessments = assessment_repo

    async def ingest_and_window(
        self,
        patient_id: str,
        observations: list[dict[str, Any]],
    ) -> VitalSignsWindow:
        """Parse, window (recent anchor), and persist a batch of observations.

        Auto-creates an active ``NORMAL`` episode for the patient when none
        exists, so callers can stream observations without pre-provisioned
        episode state.
        """
        with INGEST_DURATION.time():
            parsed = parse_batch(observations)
            if not parsed:
                raise ValueError("No valid observations parsed")

            window = window_vitals(parsed, patient_id, anchor="recent")
            if window is None:
                raise ValueError(f"Could not window vitals for {patient_id}")

            await self._vitals.append(patient_id, window)
            episode = await self._episodes.get_active_by_patient(patient_id)
            if episode is None:
                episode = await self._episodes.create(patient_id)
            await self._episodes.update_window(episode.episode_id, window)
            return window

    async def open_episode(self, patient_id: str) -> Episode:
        """Explicitly open a new clinical monitoring episode for a patient."""
        return await self._episodes.create(patient_id)

    async def get_episode(self, episode_id: str) -> Episode:
        """Fetch an episode, raising ``ValueError`` when it is unknown."""
        episode = await self._episodes.get(episode_id)
        if episode is None:
            raise ValueError(f"Unknown episode {episode_id}")
        return episode

    async def get_active_episode(self, patient_id: str) -> Episode | None:
        """Resolve the currently-active episode for a patient, if any."""
        return await self._episodes.get_active_by_patient(patient_id)

    async def get_current_window(self, episode_id: str) -> VitalSignsWindow:
        """Return the latest ``VitalSignsWindow`` for an episode's patient."""
        episode = await self.get_episode(episode_id)
        window = await self._vitals.get_window(episode.patient_id)
        if window is None:
            raise ValueError(f"No vitals stored for {episode.patient_id}")
        return window


    def _compute_trends(
        self,
        history: list[VitalSignsWindow],
    ) -> dict[str, float]:
        """Derive per-channel hourly trend slopes from a patient's history."""
        trends: dict[str, float] = {}
        for field in NUMERIC_FIELDS:
            timestamps: list[float] = []
            values: list[float] = []
            for w in history:
                value = getattr(w, field)
                if value is not None:
                    timestamps.append(w.window_end.timestamp())
                    values.append(value)
            if len(timestamps) >= 2:
                slope = compute_channel_slope(timestamps, values)
                trends[field] = slope if slope is not None else 0.0
            else:
                trends[field] = 0.0
        return trends

    async def forecast_episode(
        self,
        episode_id: str,
        horizon_minutes: int = 60,
    ) -> ForecastResult:
        """Generate a SafetyShell-sanitized trend forecast for an episode."""
        episode = await self.get_episode(episode_id)
        window = await self._vitals.get_window(episode.patient_id)
        if window is None:
            raise ValueError(
                f"No vitals stored for {episode.patient_id}"
            )

        history = await self._vitals.get_history(episode.patient_id)
        trend_per_hour = self._compute_trends(history)

        with FORECAST_DURATION.time():
            return await self._backend.forecast(window, horizon_minutes, trend_per_hour)

    async def discover_channels(self, episode_id: str) -> list[str]:
        """List the vital channels currently present in an episode's window."""
        window = await self.get_current_window(episode_id)
        channels = [f for f in NUMERIC_FIELDS if getattr(window, f) is not None]
        if window.avpu is not None:
            channels.append("avpu")
        return channels

    async def assess_episode(
        self,
        episode_id: str,
        horizon_minutes: int = 60,
    ) -> DeteriorationAssessment:
        """Run a full forecast + DDS assessment for an episode's latest window."""
        episode = await self.get_episode(episode_id)
        forecast = await self.forecast_episode(episode_id, horizon_minutes)

        score, factors = compute_dds(forecast.forecasted_vitals)
        severity = severity_from_score(score)

        # Propagate forecast-level signals (e.g. stale data / channel trends)
        # into the assessment's factor list so downstream consumers and the v2
        # / MCP envelopes surface them alongside the DDS classification.
        for factor in forecast.contributing_factors:
            if factor not in factors:
                factors.append(factor)

        assessment = DeteriorationAssessment(
            patient_id=episode.patient_id,
            dds_score=round(min(score, 20.0), 2),
            severity=severity,
            contributing_factors=factors,
        )

        await self._episodes.transition(
            episode_id, "deterioration_assessment", assessment
        )
        if self._assessments is not None:
            await self._assessments.append_assessment(episode_id, assessment)

        logger.info(
            "Episode %s assessed: DDS=%s severity=%s",
            episode_id,
            assessment.dds_score,
            assessment.severity,
        )
        return assessment
