"""Tests for FHIR ingestion and windowing."""


import pytest

from src.ingestion.fhir_parser import LOINC_CODES, parse_batch, parse_observation
from src.ingestion.windowing import window_vitals


def make_observation(loinc: str, value: float, patient_id: str = "PT-001"):
    """Helper to build a FHIR Observation."""
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


class TestFhirParser:
    def test_parse_observation_success(self):
        obs = make_observation("8867-4", 72.0)
        result = parse_observation(obs)
        assert result["patient_id"] == "PT-001"
        assert result["vital_type"] == "heart_rate"
        assert result["value"] == 72.0

    def test_parse_observation_wrong_resource_type(self):
        with pytest.raises(ValueError):
            parse_observation({"resourceType": "Patient"})

    def test_parse_observation_unknown_loinc(self):
        obs = make_observation("9999-9", 100.0)
        result = parse_observation(obs)
        assert result == {}

    def test_parse_batch_mixed(self):
        obs_list = [
            make_observation("8867-4", 72.0),
            make_observation("8480-6", 120.0),
            {"resourceType": "Patient"},  # invalid, should be skipped
        ]
        results = parse_batch(obs_list)
        assert len(results) == 2
        assert results[0]["vital_type"] == "heart_rate"
        assert results[1]["vital_type"] == "systolic_bp"

    def test_loinc_codes_complete(self):
        assert "8867-4" in LOINC_CODES
        assert "8480-6" in LOINC_CODES
        assert "8462-4" in LOINC_CODES
        assert "2708-6" in LOINC_CODES
        assert "9279-1" in LOINC_CODES
        assert "8310-5" in LOINC_CODES


class TestWindowing:
    def test_window_vitals_basic(self):
        records = [
            {"patient_id": "PT-001", "vital_type": "heart_rate", "value": 70, "timestamp": "2026-07-02T08:00:00Z"},
            {"patient_id": "PT-001", "vital_type": "heart_rate", "value": 74, "timestamp": "2026-07-02T08:02:00Z"},
            {"patient_id": "PT-001", "vital_type": "systolic_bp", "value": 120, "timestamp": "2026-07-02T08:01:00Z"},
        ]
        window = window_vitals(records, "PT-001", window_minutes=5)
        assert window is not None
        assert window.patient_id == "PT-001"
        assert window.heart_rate == 72.0  # mean of 70, 74
        assert window.systolic_bp == 120.0

    def test_window_vitals_empty(self):
        assert window_vitals([], "PT-001") is None

    def test_window_vitals_wrong_patient(self):
        records = [{"patient_id": "PT-002", "vital_type": "heart_rate", "value": 70, "timestamp": "2026-07-02T08:00:00Z"}]
        assert window_vitals(records, "PT-001") is None

    def test_window_vitals_outside_window(self):
        records = [
            {"patient_id": "PT-001", "vital_type": "heart_rate", "value": 70, "timestamp": "2026-07-02T08:00:00Z"},
            {"patient_id": "PT-001", "vital_type": "heart_rate", "value": 80, "timestamp": "2026-07-02T08:10:00Z"},  # outside 5min window
        ]
        window = window_vitals(records, "PT-001", window_minutes=5)
        assert window.heart_rate == 70.0  # only first record in window

    def test_window_vitals_non_numeric_skipped(self):
        records = [
            {"patient_id": "PT-001", "vital_type": "heart_rate", "value": "invalid", "timestamp": "2026-07-02T08:00:00Z"},
            {"patient_id": "PT-001", "vital_type": "heart_rate", "value": 80, "timestamp": "2026-07-02T08:01:00Z"},
        ]
        window = window_vitals(records, "PT-001", window_minutes=5)
        assert window.heart_rate == 80.0
