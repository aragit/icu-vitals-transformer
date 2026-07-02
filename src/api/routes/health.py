"""Health check endpoints."""

from fastapi import APIRouter, status

from src.config import settings

router = APIRouter()


@router.get("/", status_code=status.HTTP_200_OK)
async def health_check():
    """Liveness probe."""
    return {
        "status": "healthy",
        "service": settings.app_name,
        "version": settings.app_version,
    }


@router.get("/ready", status_code=status.HTTP_200_OK)
async def readiness_check():
    """Readiness probe."""
    return {
        "status": "ready",
        "service": settings.app_name,
        "version": settings.app_version,
    }
