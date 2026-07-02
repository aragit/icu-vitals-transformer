"""Tests for FastAPI endpoints."""

import pytest
import httpx

from src.main import app
from src.mcp_server.server import _vitals_store


@pytest.fixture(autouse=True)
def clear_store():
    """Clear in-memory store before each test."""
    _vitals_store.clear()
    yield


def make_fhir_obs(loinc: str, value: float, patient_id: str = "PT-001"):
    return {
        "resourceType": "Observation",
        "subject": {"reference": f"Patient/{patient_id}"},
        "code": {
            "coding": [
                {"system": "http://loinc.org", "code": loinc, "display": "Test"}
            ]
        },
        "valueQuantity": {"value": value, "unit": "bpm"},
        "effectiveDateTime": "2026-07-02T08:00:00Z",
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
        response = await client.get("/health/")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


@pytest.mark.asyncio
async def test_ingest_vitals():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        obs = make_fhir_obs("8867-4", 72.0)
        response = await client.post("/vitals/ingest", json={"observations": [obs]})
    assert response.status_code == 200
    data = response.json()
    assert data["patient_id"] == "PT-001"
    assert data["heart_rate"] == 72.0


@pytest.mark.asyncio
async def test_ingest_invalid():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/vitals/ingest", json={"observations": [{"resourceType": "Patient"}]})
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_get_current_vitals():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        obs = make_fhir_obs("8867-4", 72.0)
        await client.post("/vitals/ingest", json={"observations": [obs]})
        response = await client.get("/vitals/current/PT-001")
    assert response.status_code == 200
    data = response.json()
    assert data["patient_id"] == "PT-001"


@pytest.mark.asyncio
async def test_get_current_not_found():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/vitals/current/PT-999")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_forecast():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        obs = make_fhir_obs("8867-4", 72.0)
        await client.post("/vitals/ingest", json={"observations": [obs]})
        response = await client.get("/vitals/forecast/PT-001")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 3
    assert data[0]["severity"] == "NORMAL"


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
        await client.post("/vitals/ingest", json={"observations": obs_list})
        response = await client.get("/vitals/deterioration/PT-001")
    assert response.status_code == 200
    data = response.json()
    assert data["severity"] == "EMERGENCY"
    assert len(data["contributing_factors"]) > 0
