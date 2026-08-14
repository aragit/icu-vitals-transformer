"""Prometheus metrics endpoint (REST driving adapter)."""

from __future__ import annotations

from fastapi import APIRouter, Response

from src.observability.metrics import metrics_handler

router = APIRouter(tags=["metrics"])


@router.get("/metrics")
async def metrics() -> Response:
    """Expose Prometheus metrics in text exposition format."""
    return Response(
        content=metrics_handler(),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )
