"""Health probe endpoints (REST driving adapter)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, status

from src.config import settings
from src.dependencies import (
    get_assessment_repo,
    get_episode_repo,
    get_vitals_repo,
)
from src.ports.repository import (
    AssessmentRepository,
    EpisodeRepository,
    VitalsRepository,
)

router = APIRouter(prefix="/health", tags=["health"])

COMPONENT_NAMES = (
    "vitals_repository",
    "episode_repository",
    "assessment_repository",
)


@router.get("/liveness", status_code=status.HTTP_200_OK)
async def liveness() -> dict[str, str]:
    """Liveness probe — the process is up."""
    return {
        "status": "ok",
        "service": settings.app_name,
        "version": settings.app_version,
    }


@router.get("/readiness", status_code=status.HTTP_200_OK)
async def readiness(
    vitals: VitalsRepository = Depends(get_vitals_repo),
    episodes: EpisodeRepository = Depends(get_episode_repo),
    assessments: AssessmentRepository = Depends(get_assessment_repo),
) -> dict[str, object]:
    """Readiness probe — verifies repository state accessibility."""
    components = {
        "vitals_repository": type(vitals).__name__,
        "episode_repository": type(episodes).__name__,
        "assessment_repository": type(assessments).__name__,
    }
    return {
        "status": "ready",
        "components": components,
    }
