"""A2A REST driving adapter (feature-flagged).

Exposes:
* ``GET /.well-known/agent.json`` — the A2A agent card (from
  ``manifests/AGENT_CARD.json``).
* ``POST /a2a/tasks`` — dispatch an A2A Task to the hex core via
  ``A2ATaskHandler``.

Both endpoints are gated at runtime by ``settings.a2a_enabled`` (default
``false``): when disabled they return HTTP 404 so the endpoints cleanly vanish
for orchestrators without affecting the REST v2 or MCP surfaces.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from src.adapters.a2a.discovery import build_agent_card
from src.adapters.a2a.task_handler import A2ATaskHandler
from src.config import settings
from src.core.services.clinical_assessment import ClinicalAssessmentService
from src.dependencies import get_clinical_service

router = APIRouter(tags=["a2a"])


def _require_a2a_enabled() -> None:
    if not settings.a2a_enabled:
        raise HTTPException(status_code=404, detail="A2A adapter disabled")


@router.get("/.well-known/agent.json")
async def agent_card() -> dict[str, Any]:
    """Return the A2A agent card for capability negotiation."""
    _require_a2a_enabled()
    return build_agent_card()


@router.post("/a2a/tasks")
async def execute_a2a_task(
    request: Request,
    service: ClinicalAssessmentService = Depends(get_clinical_service),
) -> dict[str, Any]:
    """Execute an A2A task and return an Artifact payload."""
    _require_a2a_enabled()
    task: dict[str, Any] = await request.json()
    handler = A2ATaskHandler(service=service)
    try:
        return await handler.execute(task)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
