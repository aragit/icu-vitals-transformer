"""Integration tests: full FastAPI request lifecycle (baseline contract).

Exercise the end-to-end contract through ``fastapi.testclient.TestClient``:
ingest → current → forecast → deterioration. These assert the public REST
behavior documented in docs/BASELINE.md §2.
"""

import pytest
from fastapi.testclient import TestClient

from src.main import app
from src.mcp_server.server import _vitals_store

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def clear_store():
    """Isolate each test from global in-memory state."""
    _vitals_store.clear()
    yield
    _vitals_store.clear()


client = TestClient(app)


def _fhir_obs(loinc: str, value, patient_id: str = "PT-001", unit: str = "bpm",
              ts: str = "2026-07-02T08:00:30Z"):
    return {
        "resourceType": "Observation",
        "subject": {"reference": f"Patient/{patient_id}"},
        "code": {"coding": [{"system": "http://loinc.org", "code": loinc}]},
        "valueQuantity": {"value": value, "unit": unit},
        "effectiveDateTime": ts,
    }


# LOINC -> (value, unit) for a healthy baseline patient.
HEALTHY = [
    ("8867-4", 72, "bpm"),
    ("8480-6", 120, "mmHg"),
    ("8462-4", 80, "mmHg"),
    ("2708-6", 98, "%"),
    ("9279-1", 16, "/min"),
    ("8310-5", 36.5, "degC"),
]

# LOINC -> (value, unit) for a critically ill patient.
CRITICAL = [
    ("8867-4", 140, "bpm"),
    ("8480-6", 80, "mmHg"),
    ("8462-4", 50, "mmHg"),
    ("2708-6", 88, "%"),
    ("9279-1", 28, "/min"),
    ("8310-5", 34.0, "degC"),
]


def _batch(rows, patient_id="PT-001", base_minute=0):
    observations = []
    for i, (loinc, value, unit) in enumerate(rows):
        ts = f"2026-07-02T08:{base_minute:02d}:{i:02d}Z"
        observations.append(_fhir_obs(loinc, value, patient_id, unit, ts))
    return {"observations": observations}


class TestIngestContract:
    def test_ingest_full_vitals(self):
        resp = client.post("/vitals/ingest", json=_batch(HEALTHY))
        assert resp.status_code == 200
        data = resp.json()
        assert data["patient_id"] == "PT-001"
        assert data["heart_rate"] == 72.0
        assert data["systolic_bp"] == 120.0
        assert data["spo2"] == 98.0
        assert data["temperature"] == 36.5

    def test_ingest_empty_observations_returns_400(self):
        resp = client.post("/vitals/ingest", json={"observations": []})
        assert resp.status_code == 400

    def test_ingest_invalid_observation_returns_400(self):
        resp = client.post("/vitals/ingest", json={"observations": [{"resourceType": "Patient"}]})
        assert resp.status_code == 400


class TestCurrentVitalsContract:
    def test_current_after_ingest(self):
        client.post("/vitals/ingest", json=_batch(HEALTHY))
        resp = client.get("/vitals/current/PT-001")
        assert resp.status_code == 200
        data = resp.json()
        assert data["patient_id"] == "PT-001"
        assert data["heart_rate"] == 72.0

    def test_current_unknown_patient_404(self):
        resp = client.get("/vitals/current/PT-999")
        assert resp.status_code == 404


class TestForecastContract:
    def test_forecast_returns_three_horizons(self):
        client.post("/vitals/ingest", json=_batch(HEALTHY))
        resp = client.get("/vitals/forecast/PT-001")
        assert resp.status_code == 200
        forecasts = resp.json()
        assert len(forecasts) == 3
        horizons = [f["horizon_minutes"] for f in forecasts]
        assert horizons == [60, 240, 720]
        assert all(f["severity"] == "NORMAL" for f in forecasts)
        # Flat-line default: forecasted equals current for HR.
        assert forecasts[0]["forecasted_vitals"]["heart_rate"] == 72.0

    def test_forecast_unknown_patient_404(self):
        resp = client.get("/vitals/forecast/PT-999")
        assert resp.status_code == 404


class TestDeteriorationContract:
    def test_deterioration_healthy(self):
        client.post("/vitals/ingest", json=_batch(HEALTHY))
        resp = client.get("/vitals/deterioration/PT-001")
        assert resp.status_code == 200
        data = resp.json()
        assert data["patient_id"] == "PT-001"
        assert data["severity"] == "NORMAL"
        assert 0 <= data["ensemble_score"] <= 20

    def test_deterioration_critical(self):
        client.post("/vitals/ingest", json=_batch(CRITICAL))
        resp = client.get("/vitals/deterioration/PT-001")
        assert resp.status_code == 200
        data = resp.json()
        assert data["severity"] == "EMERGENCY"
        assert len(data["contributing_factors"]) > 0

    def test_deterioration_unknown_patient_404(self):
        resp = client.get("/vitals/deterioration/PT-999")
        assert resp.status_code == 404


class TestFullLifecycle:
    def test_ingest_current_forecast_deterioration(self):
        # Full FastAPI TestClient lifecycle per the epic.
        ingest = client.post("/vitals/ingest", json=_batch(HEALTHY))
        assert ingest.status_code == 200

        current = client.get("/vitals/current/PT-001")
        assert current.status_code == 200
        assert current.json()["heart_rate"] == 72.0

        forecast = client.get("/vitals/forecast/PT-001")
        assert forecast.status_code == 200
        assert len(forecast.json()) == 3

        deterioration = client.get("/vitals/deterioration/PT-001")
        assert deterioration.status_code == 200
        assert deterioration.json()["severity"] == "NORMAL"
