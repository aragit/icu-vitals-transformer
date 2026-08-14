"""MCP tool definitions for ICU Vitals Transformer (MCP driving adapter).

Tools delegate to the hexagon's ``ClinicalAssessmentService`` and return dicts
that embed the mandatory ``_meta`` envelope (clinical disclaimer + data
freshness), mirroring the v2 REST surface. Tools are declared ``async`` so they
can await the async service layer directly inside FastMCP's event loop.
"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP
from src.adapters.mcp.mrtr import resolve_single_episode
from src.adapters.rest.metadata import build_meta, freshness_seconds
from src.core.services.clinical_assessment import ClinicalAssessmentService
from src.dependencies import get_clinical_service
from src.observability.metrics import MCP_TOOL_CALLS


def register_tools(server: FastMCP) -> None:
    """Register all MCP tools onto the given server."""

    def service() -> ClinicalAssessmentService:
        return get_clinical_service()

    @server.tool()
    async def ingest_vitals(
        patient_id: str,
        observations: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Ingest a batch of FHIR observations and resolve/create the active episode.

        Args:
            patient_id: Canonical identifier of the patient.
            observations: List of FHIR observation JSON dicts.
        """
        MCP_TOOL_CALLS.inc()
        svc = service()
        window = await svc.ingest_and_window(patient_id, observations)
        episode = await svc.get_active_episode(patient_id)
        return {
            **window.model_dump(mode="json"),
            "episode_id": episode.episode_id if episode is not None else "",
            "_meta": build_meta(freshness_seconds(window.window_end)),
        }

    @server.tool()
    async def get_forecast(
        episode_id: str,
        horizon_minutes: int = 60,
    ) -> dict[str, Any]:
        """Generate a SafetyShell-sanitized forecast for an episode.

        Args:
            episode_id: Episode to forecast.
            horizon_minutes: Forecast horizon in minutes (60-720).
        """
        MCP_TOOL_CALLS.inc()
        svc = service()
        forecast = await svc.forecast_episode(episode_id, horizon_minutes)
        return {
            **forecast.model_dump(mode="json"),
            "_meta": build_meta(forecast.data_freshness_seconds),
        }

    @server.tool()
    async def get_deterioration_index(episode_id: str) -> dict[str, Any]:
        """Compute the DDS deterioration index and severity tier for an episode.

        Args:
            episode_id: Episode to evaluate.
        """
        MCP_TOOL_CALLS.inc()
        svc = service()
        assessment = await svc.assess_episode(episode_id)
        window = await svc.get_current_window(episode_id)
        return {
            **assessment.model_dump(mode="json"),
            "episode_id": episode_id,
            "_meta": build_meta(freshness_seconds(window.window_end)),
        }

    @server.tool()
    async def discover_episode(patient_id: str) -> dict[str, Any]:
        """Discover the currently-active episode(s) for a patient.

        Args:
            patient_id: Canonical identifier of the patient.

        Returns the active episode, or a structured ``mrtr`` disambiguation
        payload when multiple active episodes exist and no ``episode_id`` was
        supplied.
        """
        MCP_TOOL_CALLS.inc()
        svc = service()
        candidates = await svc._episodes.get_all_active_by_patient(patient_id)
        mrtr = resolve_single_episode(patient_id, candidates, None)
        if mrtr is not None:
            return mrtr
        episode = candidates[0] if candidates else None
        return {
            "patient_id": patient_id,
            "episode_id": episode.episode_id if episode is not None else None,
            "state": episode.state.value if episode is not None else None,
            "_meta": build_meta(0),
        }
