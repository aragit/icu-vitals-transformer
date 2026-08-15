"""Integration tests for the v2 REST driving adapter."""

import httpx
import pytest

from src.dependencies import reset_dependencies
from src.main import app
from src.vitals_state import _vitals_store

BASE = "http://test"


@pytest.fixture(autouse=True)
def clear_state():
    """Reset DI singletons and legacy raw store before each test."""
    reset_dependencies()
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


def assert_meta(payload: dict) -> None:
    meta = payload["_meta"]
    assert isinstance(meta["data_freshness_seconds"], int)
    assert meta["data_freshness_seconds"] >= 0


@pytest.mark.asyncio
async def test_liveness_probe():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url=BASE) as client:
        response = await client.get("/health/liveness")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_readiness_probe():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url=BASE) as client:
        response = await client.get("/health/readiness")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"
    assert set(data["components"]) == {
        "vitals_repository",
        "episode_repository",
        "assessment_repository",
    }


@pytest.mark.asyncio
async def test_metrics_endpoint_prometheus_format():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url=BASE) as client:
        response = await client.get("/metrics")
    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]
    for metric in (b"vitals_ingested_total", b"forecasts_generated_total"):
        assert metric in response.content


@pytest.mark.asyncio
async def test_ingest_vitals_v2():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url=BASE) as client:
        obs = [make_fhir_obs("8867-4", 72.0), make_fhir_obs("8480-6", 95.0)]
        response = await client.post(
            "/v2/vitals/ingest",
            json={"patient_id": "PT-001", "observations": obs},
        )
    assert response.status_code == 200
    data = response.json()
    assert data["patient_id"] == "PT-001"
    assert data["heart_rate"] == 72.0
    assert data["episode_id"].startswith("E-")
    assert len(data["episode_id"]) > len("PT-001") + 2  # UUID suffix present
    assert_meta(data)


@pytest.mark.asyncio
async def test_open_episode_v2():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url=BASE) as client:
        response = await client.post("/v2/patients/PT-009/episodes")
    assert response.status_code == 200
    data = response.json()
    assert data["episode_id"].startswith("E-")
    assert len(data["episode_id"]) > len("PT-009") + 2  # UUID suffix present
    assert data["patient_id"] == "PT-009"
    assert_meta(data)


@pytest.mark.asyncio
async def test_current_window_v2():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url=BASE) as client:
        obs = [make_fhir_obs("8867-4", 74.0, patient_id="PT-002")]
        ingest = await client.post(
            "/v2/vitals/ingest",
            json={"patient_id": "PT-002", "observations": obs},
        )
        episode_id = ingest.json()["episode_id"]
        response = await client.get(f"/v2/episodes/{episode_id}/current")
    assert response.status_code == 200
    data = response.json()
    assert data["heart_rate"] == 74.0
    assert data["episode_id"] == episode_id
    assert_meta(data)


@pytest.mark.asyncio
async def test_forecast_v2():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url=BASE) as client:
        obs = [
            make_fhir_obs("8867-4", 74.0, patient_id="PT-003"),
            make_fhir_obs("8480-6", 97.0, patient_id="PT-003"),
        ]
        ingest = await client.post(
            "/v2/vitals/ingest",
            json={"patient_id": "PT-003", "observations": obs},
        )
        episode_id = ingest.json()["episode_id"]
        response = await client.get(
            f"/v2/episodes/{episode_id}/forecast?horizon_minutes=60"
        )
    assert response.status_code == 200
    data = response.json()
    assert "forecasted_vitals" in data
    assert data["data_freshness_seconds"] >= 0
    assert_meta(data)


@pytest.mark.asyncio
async def test_deterioration_v2():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url=BASE) as client:
        obs = [
            make_fhir_obs("8867-4", 74.0, patient_id="PT-004"),
            make_fhir_obs("8480-6", 97.0, patient_id="PT-004"),
        ]
        ingest = await client.post(
            "/v2/vitals/ingest",
            json={"patient_id": "PT-004", "observations": obs},
        )
        episode_id = ingest.json()["episode_id"]
        response = await client.get(f"/v2/episodes/{episode_id}/deterioration")
    assert response.status_code == 200
    data = response.json()
    assert "dds_score" in data
    assert data["episode_id"] == episode_id
    assert_meta(data)


@pytest.mark.asyncio
async def test_discovery_v2():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url=BASE) as client:
        obs = [make_fhir_obs("8867-4", 74.0, patient_id="PT-005")]
        ingest = await client.post(
            "/v2/vitals/ingest",
            json={"patient_id": "PT-005", "observations": obs},
        )
        episode_id = ingest.json()["episode_id"]
        response = await client.get(f"/v2/episodes/{episode_id}/discovery")
    assert response.status_code == 200
    data = response.json()
    assert "heart_rate" in data["channels"]
    assert_meta(data)


@pytest.mark.asyncio
async def test_unknown_episode_returns_404():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url=BASE) as client:
        response = await client.get("/v2/episodes/E-MISSING/current")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_mismatched_patient_ingest_returns_400():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url=BASE) as client:
        obs = [make_fhir_obs("8867-4", 72.0, patient_id="PT-OTHER")]
        response = await client.post(
            "/v2/vitals/ingest",
            json={"patient_id": "PT-001", "observations": obs},
        )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_correlation_id_echoed():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url=BASE) as client:
        response = await client.get(
            "/health/liveness", headers={"X-Request-ID": "corr-123"}
        )
    assert response.headers["X-Request-ID"] == "corr-123"


@pytest.mark.asyncio
async def test_correlation_id_generated():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url=BASE) as client:
        response = await client.get("/health/liveness")
    assert response.headers["X-Request-ID"]
