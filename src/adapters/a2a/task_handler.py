"""A2A task handler — translates A2A Task payloads into hex-core actions.

Accepts an A2A-style Task (a dict with an ``action`` plus ``parameters``),
delegates to ``ClinicalAssessmentService``, and returns a standard A2A Artifact
envelope whose ``data`` part contains the clinical result together with the
mandatory ``_meta`` safety-freshness advisory.
"""

from __future__ import annotations

from typing import Any

from src.adapters.rest.metadata import build_meta, freshness_seconds
from src.core.services.clinical_assessment import ClinicalAssessmentService
from src.dependencies import get_clinical_service

SUPPORTED_ACTIONS = ("ingest_vitals", "get_forecast", "get_deterioration_index")


class A2ATaskHandler:
    """Dispatch an A2A task payload to the ClinicalAssessmentService."""

    def __init__(self, service: ClinicalAssessmentService | None = None) -> None:
        self._service: ClinicalAssessmentService = service or get_clinical_service()

    @staticmethod
    def extract(task: dict[str, Any]) -> tuple[str, dict[str, Any], str]:
        """Normalize an A2A Task into ``(action, parameters, task_id)``.

        Supports both the standard A2A ``message.parts[].data`` form and a
        flat top-level ``{action, parameters}`` shorthand.
        """
        task_id = task.get("id") or task.get("sessionId") or "a2a-task"
        payload: dict[str, Any] = {}
        message = task.get("message") or {}
        for part in message.get("parts") or []:
            if part.get("kind") == "data" and isinstance(part.get("data"), dict):
                payload = part["data"]
                break
        if not payload:
            payload = task.get("parameters") or {}
        action = payload.get("action", "")
        parameters = payload.get("parameters") or {}
        return str(action), dict(parameters), str(task_id)

    async def execute(self, task: dict[str, Any]) -> dict[str, Any]:
        """Run the requested action and wrap the result as an A2A Artifact."""
        action, params, task_id = self.extract(task)
        if action not in SUPPORTED_ACTIONS:
            raise ValueError(f"Unsupported A2A action: {action!r}")

        service = self._service
        if action == "ingest_vitals":
            window = await service.ingest_and_window(
                params["patient_id"], params.get("observations", [])
            )
            episode = await service.get_active_episode(params["patient_id"])
            result = {
                **window.model_dump(mode="json"),
                "episode_id": episode.episode_id if episode is not None else "",
            }
            meta = build_meta(freshness_seconds(window.window_end))

        elif action == "get_forecast":
            forecast = await service.forecast_episode(
                params["episode_id"], int(params.get("horizon_minutes", 60))
            )
            result = {
                **forecast.model_dump(mode="json"),
                "episode_id": params["episode_id"],
            }
            meta = build_meta(forecast.data_freshness_seconds)

        else:  # get_deterioration_index
            assessment = await service.assess_episode(
                params["episode_id"], int(params.get("horizon_minutes", 60))
            )
            window = await service.get_current_window(params["episode_id"])
            result = {
                **assessment.model_dump(mode="json"),
                "episode_id": params["episode_id"],
            }
            meta = build_meta(freshness_seconds(window.window_end))

        result["_meta"] = meta
        return {
            "id": task_id,
            "status": {"state": "completed"},
            "artifacts": [
                {
                    "id": f"{task_id}:artifact",
                    "name": "icu-vitals-transformer:result",
                    "description": (
                        "Deterministic ICU vitals forecast / DDS assessment artifact"
                    ),
                    "parts": [{"kind": "data", "data": result}],
                }
            ],
        }
