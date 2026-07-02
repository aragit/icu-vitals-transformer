"""Tests for MCP server tools."""

import json
import pytest

from src.mcp_server.server import _vitals_store, _handle_ingest, _handle_forecast, _handle_deterioration


@pytest.fixture(autouse=True)
def clear_store():
    """Clear in-memory store before each test."""
    _vitals_store.clear()
    yield


def make_fhir_obs(loinc: str, value: float, patient_id: str = "PT-001"):
    """Helper to build FHIR Observation."""
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
async def test_ingest_single_observation():
    obs = make_fhir_obs("8867-4", 72.0)
    result = await _handle_ingest({"patient_id": "PT-001", "observations": [obs]})
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["patient_id"] == "PT-001"
    assert data["heart_rate"] == 72.0


@pytest.mark.asyncio
async def test_ingest_invalid_observation():
    result = await _handle_ingest({"patient_id": "PT-001", "observations": [{"resourceType": "Patient"}]})
    data = json.loads(result[0].text)
    assert "error" in data


@pytest.mark.asyncio
async def test_ingest_empty():
    result = await _handle_ingest({"patient_id": "PT-001", "observations": []})
    data = json.loads(result[0].text)
    assert "error" in data


@pytest.mark.asyncio
async def test_forecast_after_ingest():
    obs = make_fhir_obs("8867-4", 72.0)
    await _handle_ingest({"patient_id": "PT-001", "observations": [obs]})

    result = await _handle_forecast({"patient_id": "PT-001", "horizon_minutes": 60})
    data = json.loads(result[0].text)
    assert data["patient_id"] == "PT-001"
    assert data["horizon_minutes"] == 60
    assert "severity" in data


@pytest.mark.asyncio
async def test_forecast_no_data():
    result = await _handle_forecast({"patient_id": "PT-999", "horizon_minutes": 60})
    data = json.loads(result[0].text)
    assert "error" in data


@pytest.mark.asyncio
async def test_deterioration_normal():
    obs = make_fhir_obs("8867-4", 72.0)
    await _handle_ingest({"patient_id": "PT-001", "observations": [obs]})

    result = await _handle_deterioration({"patient_id": "PT-001"})
    data = json.loads(result[0].text)
    assert data["patient_id"] == "PT-001"
    assert data["severity"] == "NORMAL"


@pytest.mark.asyncio
async def test_deterioration_emergency():
    obs_list = [
        make_fhir_obs("8867-4", 140.0, "PT-002"),   # HR critical
        make_fhir_obs("8480-6", 80.0, "PT-002"),    # SBP low
        make_fhir_obs("2708-6", 88.0, "PT-002"),    # SpO2 severe
        make_fhir_obs("9279-1", 28.0, "PT-002"),    # RR critical
    ]
    await _handle_ingest({"patient_id": "PT-002", "observations": obs_list})

    result = await _handle_deterioration({"patient_id": "PT-002"})
    data = json.loads(result[0].text)
    assert data["patient_id"] == "PT-002"
    assert data["severity"] == "EMERGENCY"
    assert len(data["contributing_factors"]) > 0
