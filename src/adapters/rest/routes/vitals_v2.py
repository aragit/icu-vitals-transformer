"""Episode-aware v2 REST endpoints (REST driving adapter).

These routes delegate to the hexagon's ``ClinicalAssessmentService`` (obtained
via ``Depends(get_clinical_service)``) and wrap every response in the standard
``_meta`` envelope (clinical disclaimer + data freshness) mandated by Phase 4.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from src.adapters.rest.metadata import build_meta, freshness_seconds
from src.core.domain.vitals import VitalSignsWindow
from src.core.services.clinical_assessment import ClinicalAssessmentService
from src.dependencies import get_clinical_service

router = APIRouter(prefix="/v2", tags=["v2"])


class VitalsIngestRequest(BaseModel):
    """Request body for ``POST /v2/vitals/ingest``."""

    patient_id: str
    observations: list[dict[str, Any]]


def _window_payload(window: VitalSignsWindow, episode_id: str) -> dict[str, Any]:
    return {
        **window.model_dump(mode="json"),
        "episode_id": episode_id,
        "_meta": build_meta(freshness_seconds(window.window_end)),
    }


@router.post("/vitals/ingest")
async def ingest_vitals(
    request: VitalsIngestRequest,
    service: ClinicalAssessmentService = Depends(get_clinical_service),
) -> dict[str, Any]:
    """Ingest FHIR observations; auto-resolve or create the active episode."""
    try:
        window = await service.ingest_and_window(
            request.patient_id, request.observations
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    episode = await service.get_active_episode(request.patient_id)
    episode_id = episode.episode_id if episode is not None else ""
    return _window_payload(window, episode_id)


@router.post("/patients/{patient_id}/episodes")
async def open_episode(
    patient_id: str,
    service: ClinicalAssessmentService = Depends(get_clinical_service),
) -> dict[str, Any]:
    """Explicitly open a new clinical monitoring episode for a patient."""
    episode = await service.open_episode(patient_id)
    return {
        **episode.model_dump(mode="json"),
        "_meta": build_meta(0),
    }


@router.get("/episodes/{episode_id}/current")
async def get_current_window(
    episode_id: str,
    service: ClinicalAssessmentService = Depends(get_clinical_service),
) -> dict[str, Any]:
    """Retrieve the latest ``VitalSignsWindow`` for an episode."""
    try:
        window = await service.get_current_window(episode_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _window_payload(window, episode_id)


@router.get("/episodes/{episode_id}/forecast")
async def forecast_episode(
    episode_id: str,
    horizon_minutes: int = Query(60, ge=60, le=720),
    service: ClinicalAssessmentService = Depends(get_clinical_service),
) -> dict[str, Any]:
    """Generate a SafetyShell-sanitized trend forecast for an episode."""
    try:
        forecast = await service.forecast_episode(episode_id, horizon_minutes)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        **forecast.model_dump(mode="json"),
        "_meta": build_meta(forecast.data_freshness_seconds),
    }


@router.get("/episodes/{episode_id}/deterioration")
async def deterioration_episode(
    episode_id: str,
    service: ClinicalAssessmentService = Depends(get_clinical_service),
) -> dict[str, Any]:
    """Evaluate DDS index and severity tier for an episode."""
    try:
        assessment = await service.assess_episode(episode_id)
        window = await service.get_current_window(episode_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        **assessment.model_dump(mode="json"),
        "episode_id": episode_id,
        "_meta": build_meta(freshness_seconds(window.window_end)),
    }


@router.get("/episodes/{episode_id}/discovery")
async def discover_channels(
    episode_id: str,
    service: ClinicalAssessmentService = Depends(get_clinical_service),
) -> dict[str, Any]:
    """List the active vital channels present in an episode's latest window."""
    try:
        channels = await service.discover_channels(episode_id)
        window = await service.get_current_window(episode_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "episode_id": episode_id,
        "channels": channels,
        "_meta": build_meta(freshness_seconds(window.window_end)),
    }
