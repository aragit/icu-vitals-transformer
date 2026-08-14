"""Contract tests for the A2A Agent-to-Agent facade (Phase 7).

Validates the A2A discovery card and the ``POST /a2a/tasks`` task dispatcher,
including the feature-flag boundary: when ``A2A_ENABLED`` is false all A2A
routes return 404 and neither REST v2 nor MCP are affected.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from src.config import settings
from src.dependencies import reset_dependencies
from src.main import app
from src.mcp_server.server import _vitals_store
from tests.e2e.factories import make_fhir_obs  # noqa: F401  (re-exported fixture data)

BASE = "http://test"


@pytest.fixture(autouse=True)
def _reset_state():
    reset_dependencies()
    _vitals_store.clear()
    # A2A is off by default; restore after each test.
    original = settings.a2a_enabled
    settings.a2a_enabled = original
    yield
    settings.a2a_enabled = original
    reset_dependencies()
    _vitals_store.clear()


def _client() -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url=BASE)


def _task(action: str, parameters: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build an A2A-style task payload (standard message.parts[].data form)."""
    return {
        "id": "task-1",
        "sessionId": "sess-1",
        "message": {
            "role": "user",
            "parts": [
                {
                    "kind": "data",
                    "data": {
                        "action": action,
                        "parameters": parameters or {},
                    },
                }
            ],
        },
    }


def _flatten_artifact(task_response: dict[str, Any]) -> dict[str, Any]:
    return task_response["artifacts"][0]["parts"][0]["data"]


@pytest.mark.asyncio
async def test_a2a_disabled_by_default_returns_404():
    settings.a2a_enabled = False
    async with _client() as client:
        card = await client.get("/.well-known/agent.json")
        assert card.status_code == 404
        task = await client.post("/a2a/tasks", json=_task("ingest_vitals"))
        assert task.status_code == 404


@pytest.mark.asyncio
async def test_agent_card_served_when_enabled():
    settings.a2a_enabled = True
    async with _client() as client:
        response = await client.get("/.well-known/agent.json")
    assert response.status_code == 200
    card = response.json()
    assert card["name"] == "icu-vitals-transformer"
    assert card["version"] == "0.9.0"
    assert card["schema"] == "a2a-agent-card/v1"
    assert "skills" in card and "operationalGuardrails" in card
    assert card["operationalGuardrails"]["auth"]["scheme"] == "CIMD-JWT"


@pytest.mark.asyncio
async def test_ingest_task_returns_structured_artifact():
    settings.a2a_enabled = True
    observations = [make_fhir_obs("8867-4", 72.0), make_fhir_obs("8480-6", 95.0)]
    task = _task("ingest_vitals", {"patient_id": "PT-001", "observations": observations})
    async with _client() as client:
        response = await client.post("/a2a/tasks", json=task)
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == "task-1"
    assert body["status"]["state"] == "completed"
    data = _flatten_artifact(body)
    assert data["episode_id"] == "E-PT-001"
    assert data["heart_rate"] == 72.0
    assert data["patient_id"] == "PT-001"
    meta = data["_meta"]
    assert isinstance(meta["data_freshness_seconds"], int)
    assert meta["clinical_disclaimer"]


@pytest.mark.asyncio
async def test_forecast_task_returns_artifact():
    settings.a2a_enabled = True
    observations = [
        make_fhir_obs("8867-4", 80.0, patient_id="PT-002",
                     effective="2026-07-02T07:00:00Z"),
        make_fhir_obs("8867-4", 85.0, patient_id="PT-002",
                     effective="2026-07-02T07:30:00Z"),
    ]
    async with _client() as client:
        ingest = await client.post(
            "/a2a/tasks", json=_task("ingest_vitals", {
                "patient_id": "PT-002", "observations": observations,
            })
        )
        assert ingest.status_code == 200
        forecast = await client.post(
            "/a2a/tasks", json=_task("get_forecast", {
                "episode_id": "E-PT-002", "horizon_minutes": 60,
            })
        )
    assert forecast.status_code == 200
    body = forecast.json()
    assert body["status"]["state"] == "completed"
    data = _flatten_artifact(body)
    assert data["patient_id"] == "PT-002"
    assert data["episode_id"] == "E-PT-002"
    assert "forecasted_vitals" in data
    assert "uncertainty_lower" in data and "uncertainty_upper" in data
    assert data["_meta"]["data_freshness_seconds"] >= 0


@pytest.mark.asyncio
async def test_deterioration_task_returns_artifact():
    settings.a2a_enabled = True
    observations = [make_fhir_obs("8867-4", 110.0, patient_id="PT-003"),
                    make_fhir_obs("8867-4", 115.0, patient_id="PT-003",
                                  effective="2026-07-02T08:30:00Z")]
    async with _client() as client:
        await client.post("/a2a/tasks", json=_task("ingest_vitals", {
            "patient_id": "PT-003", "observations": observations,
        }))
        response = await client.post("/a2a/tasks", json=_task(
            "get_deterioration_index", {"episode_id": "E-PT-003", "horizon_minutes": 60}
        ))
    assert response.status_code == 200
    data = _flatten_artifact(response.json())
    assert data["episode_id"] == "E-PT-003"
    assert "ensemble_score" in data
    assert "severity" in data


@pytest.mark.asyncio
async def test_unsupported_action_returns_400():
    settings.a2a_enabled = True
    task = _task("launch_missiles", {})
    async with _client() as client:
        response = await client.post("/a2a/tasks", json=task)
    assert response.status_code == 400
    assert "launch_missiles" in response.json()["detail"]
