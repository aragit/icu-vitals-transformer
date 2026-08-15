"""MCP tool definitions for ICU Vitals Transformer (MCP driving adapter).

Tools delegate to the hexagon's ``ClinicalAssessmentService`` and return dicts
that embed the mandatory ``_meta`` envelope (clinical disclaimer + data
freshness), mirroring the v2 REST surface. Tools are declared ``async`` so they
can await the async service layer directly inside FastMCP's event loop.
"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP
from src.adapters.mcp.discovery import discover_capabilities as _discover_capabilities
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
    async def discover_episode(
        patient_id: str,
        episode_id: str | None = None,
    ) -> dict[str, Any]:
        """Return the active episode for a patient, or all candidates if ambiguous.

        Args:
            patient_id: Canonical identifier of the patient.
            episode_id: Optional explicit episode to resolve.

        When ``episode_id`` is supplied it is resolved directly. Otherwise, if
        exactly one active episode exists it is returned; if multiple active
        episodes exist an ``episodes`` array is returned so the caller can pick;
        if none exist ``episode_id`` is ``None``.
        """
        MCP_TOOL_CALLS.inc()
        svc = service()

        # If episode_id is explicitly provided, resolve it directly
        if episode_id:
            episode = await svc.get_episode(episode_id)
            if episode is None or episode.patient_id != patient_id:
                raise ValueError(f"Episode {episode_id} not found for patient {patient_id}")
            return {
                "patient_id": patient_id,
                "episode_id": episode.episode_id,
                "state": episode.state.value,
                "_meta": build_meta(0),
            }

        candidates = await svc._episodes.get_all_active_by_patient(patient_id)

        if not candidates:
            return {
                "patient_id": patient_id,
                "episode_id": None,
                "state": None,
                "_meta": build_meta(0),
            }

        if len(candidates) == 1:
            episode = candidates[0]
            return {
                "patient_id": patient_id,
                "episode_id": episode.episode_id,
                "state": episode.state.value,
                "_meta": build_meta(0),
            }

        # Multiple active episodes — return structured data, not a conversation prompt
        return {
            "patient_id": patient_id,
            "episodes": [
                {
                    "episode_id": ep.episode_id,
                    "state": ep.state.value,
                    "created_at": ep.created_at.isoformat(),
                }
                for ep in candidates
            ],
            "_meta": build_meta(0),
        }

    @server.tool()
    async def discover_capabilities() -> dict[str, Any]:
        """Return the server capability matrix (tools, safety bounds)."""
        MCP_TOOL_CALLS.inc()
        caps = _discover_capabilities()
        return {
            **caps,
            "_meta": build_meta(0),
        }
