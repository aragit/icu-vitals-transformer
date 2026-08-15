"""Integration tests: full v2 REST lifecycle (baseline contract).

Ingest -> current -> forecast -> deterioration, each scoped to an episode via
``POST /v2/patients/{id}/episodes`` / ``POST /v2/vitals/ingest``. Asserts the
public v2 REST behaviour documented in docs/BASELINE.md §2.
"""

import pytest
from fastapi.testclient import TestClient

from src.dependencies import reset_dependencies
from src.main import app
from src.vitals_state import _vitals_store

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def clear_state():
    """Isolate each test from global state."""
    reset_dependencies()
    _vitals_store.clear()
    yield
    _vitals_store.clear()


client = TestClient(app)


def _disclaimer() -> str:
    from src.core.domain.disclaimer import CLINICAL_SAFETY_DISCLAIMER

    return CLINICAL_SAFETY_DISCLAIMER


def assert_meta(payload: dict) -> None:
    meta = payload["_meta"]
    assert meta["clinical_disclaimer"] == _disclaimer()
    assert isinstance(meta["data_freshness_seconds"], int)
    assert meta["data_freshness_seconds"] >= 0


def _fhir_obs(loinc: str, value, patient_id="PT-001", unit="bpm",
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
    return {"patient_id": patient_id, "observations": observations}


def _ingest_then_episode(patient_id="PT-001", rows=None):
    rows = rows or HEALTHY
    resp = client.post("/v2/vitals/ingest", json=_batch(rows, patient_id))
    assert resp.status_code == 200
    return resp.json()["episode_id"]


class TestIngestContract:
    def test_ingest_full_vitals(self):
        resp = client.post("/v2/vitals/ingest", json=_batch(HEALTHY))
        assert resp.status_code == 200
        data = resp.json()
        assert data["patient_id"] == "PT-001"
        assert data["heart_rate"] == 72.0
        assert data["systolic_bp"] == 120.0
        assert data["spo2"] == 98.0
        assert data["temperature"] == 36.5
        assert data["episode_id"] == "E-PT-001"
        assert_meta(data)

    def test_ingest_empty_observations_returns_400(self):
        resp = client.post("/v2/vitals/ingest", json={"patient_id": "PT-001", "observations": []})
        assert resp.status_code == 400

    def test_ingest_invalid_observation_returns_400(self):
        resp = client.post(
            "/v2/vitals/ingest",
            json={"patient_id": "PT-001", "observations": [{"resourceType": "Patient"}]},
        )
        assert resp.status_code == 400


class TestCurrentVitalsContract:
    def test_current_after_ingest(self):
        eid = _ingest_then_episode()
        resp = client.get(f"/v2/episodes/{eid}/current")
        assert resp.status_code == 200
        data = resp.json()
        assert data["patient_id"] == "PT-001"
        assert data["heart_rate"] == 72.0
        assert data["episode_id"] == eid
        assert_meta(data)

    def test_current_unknown_episode_404(self):
        resp = client.get("/v2/episodes/E-MISSING/current")
        assert resp.status_code == 404


class TestForecastContract:
    def test_forecast_returned(self):
        eid = _ingest_then_episode()
        resp = client.get(f"/v2/episodes/{eid}/forecast", params={"horizon_minutes": 60})
        assert resp.status_code == 200
        data = resp.json()
        assert data["horizon_minutes"] == 60
        assert "forecasted_vitals" in data
        assert_meta(data)

    def test_forecast_unknown_episode_404(self):
        resp = client.get("/v2/episodes/E-MISSING/forecast")
        assert resp.status_code == 404


class TestDeteriorationContract:
    def test_deterioration_healthy(self):
        eid = _ingest_then_episode()
        resp = client.get(f"/v2/episodes/{eid}/deterioration")
        assert resp.status_code == 200
        data = resp.json()
        assert data["patient_id"] == "PT-001"
        assert data["severity"] == "NORMAL"
        assert 0 <= data["ensemble_score"] <= 20
        assert_meta(data)

    def test_deterioration_critical(self):
        eid = _ingest_then_episode(rows=CRITICAL)
        resp = client.get(f"/v2/episodes/{eid}/deterioration")
        assert resp.status_code == 200
        data = resp.json()
        assert data["severity"] == "EMERGENCY"
        assert len(data["contributing_factors"]) > 0
        assert_meta(data)

    def test_deterioration_unknown_episode_404(self):
        resp = client.get("/v2/episodes/E-MISSING/deterioration")
        assert resp.status_code == 404


class TestFullLifecycle:
    def test_ingest_current_forecast_deterioration(self):
        eid = _ingest_then_episode()
        assert client.get(f"/v2/episodes/{eid}/current").status_code == 200

        forecast = client.get(f"/v2/episodes/{eid}/forecast", params={"horizon_minutes": 60})
        assert forecast.status_code == 200
        assert "forecasted_vitals" in forecast.json()

        det = client.get(f"/v2/episodes/{eid}/deterioration")
        assert det.status_code == 200
        assert det.json()["severity"] == "NORMAL"
