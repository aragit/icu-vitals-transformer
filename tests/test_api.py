"""Tests for v2 FastAPI endpoints (episode-keyed).

Replaces the legacy v1 ``/vitals/*`` contract: every vital-sign request is
scoped to an episode created via ``POST /v2/patients/{id}/episodes`` (or
implicitly by ``POST /v2/vitals/ingest``). See docs/BASELINE.md §2 (v2 REST).
"""

import httpx
import pytest

from src.dependencies import reset_dependencies
from src.main import app
from src.vitals_state import _vitals_store


@pytest.fixture(autouse=True)
def clear_state():
    """Reset DI singletons and the shared raw store before each test."""
    reset_dependencies()
    _vitals_store.clear()
    yield
    _vitals_store.clear()


def assert_meta(payload: dict) -> None:
    meta = payload["_meta"]
    assert isinstance(meta["data_freshness_seconds"], int)
    assert meta["data_freshness_seconds"] >= 0


def make_fhir_obs(loinc: str, value, patient_id: str = "PT-001", unit: str = "bpm",
                  ts: str = "2026-07-02T08:00:30Z"):
    return {
        "resourceType": "Observation",
        "subject": {"reference": f"Patient/{patient_id}"},
        "code": {"coding": [{"system": "http://loinc.org", "code": loinc, "display": "Test"}]},
        "valueQuantity": {"value": value, "unit": unit},
        "effectiveDateTime": ts,
    }


@pytest.mark.asyncio
async def test_root():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "icu-vitals-transformer"
    assert data["status"] == "operational"


@pytest.mark.asyncio
async def test_health():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health/readiness")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"


@pytest.mark.asyncio
async def test_ingest_vitals():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        obs = make_fhir_obs("8867-4", 72.0)
        response = await client.post(
            "/v2/vitals/ingest",
            json={"patient_id": "PT-001", "observations": [obs]},
        )
    assert response.status_code == 200
    data = response.json()
    assert data["patient_id"] == "PT-001"
    assert data["heart_rate"] == 72.0
    episode_id = data["episode_id"]
    assert episode_id.startswith("E-")
    assert len(episode_id) > len("PT-001") + 2  # UUID suffix present
    assert_meta(data)


@pytest.mark.asyncio
async def test_ingest_invalid():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        body = {"patient_id": "PT-001", "observations": [{"resourceType": "Patient"}]}
        response = await client.post("/v2/vitals/ingest", json=body)
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_get_current_vitals():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        obs = make_fhir_obs("8867-4", 72.0)
        resp = await client.post(
            "/v2/vitals/ingest",
            json={"patient_id": "PT-001", "observations": [obs]},
        )
        episode_id = resp.json()["episode_id"]
        response = await client.get(f"/v2/episodes/{episode_id}/current")
    assert response.status_code == 200
    data = response.json()
    assert data["patient_id"] == "PT-001"
    assert data["heart_rate"] == 72.0
    assert data["episode_id"] == episode_id
    assert_meta(data)


@pytest.mark.asyncio
async def test_get_current_not_found():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/v2/episodes/E-MISSING/current")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_forecast():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        obs = make_fhir_obs("8867-4", 72.0)
        resp = await client.post(
            "/v2/vitals/ingest",
            json={"patient_id": "PT-001", "observations": [obs]},
        )
        episode_id = resp.json()["episode_id"]
        response = await client.get(
            f"/v2/episodes/{episode_id}/forecast", params={"horizon_minutes": 60}
        )
    assert response.status_code == 200
    data = response.json()
    assert data["horizon_minutes"] == 60
    assert "forecasted_vitals" in data
    assert_meta(data)


@pytest.mark.asyncio
async def test_get_deterioration():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        obs_list = [
            make_fhir_obs("8867-4", 140.0),
            make_fhir_obs("8480-6", 80.0),
            make_fhir_obs("2708-6", 88.0),
            make_fhir_obs("9279-1", 28.0),
        ]
        resp = await client.post(
            "/v2/vitals/ingest",
            json={"patient_id": "PT-001", "observations": obs_list},
        )
        episode_id = resp.json()["episode_id"]
        response = await client.get(f"/v2/episodes/{episode_id}/deterioration")
    assert response.status_code == 200
    data = response.json()
    assert data["severity"] == "EMERGENCY"
    assert "dds_score" in data
    assert len(data["contributing_factors"]) > 0
    assert_meta(data)


@pytest.mark.asyncio
async def test_forecast_unknown_episode_404():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/v2/episodes/E-MISSING/forecast")
    assert response.status_code == 404
