"""Unit tests for the FHIR R4 Observation parser (baseline contract).

These tests pin the *current* (baseline) parsing behavior of
``src.core.ingestion.fhir_parser``. See docs/BASELINE.md §5.1 and §6 (legacy
limitations): notably, AVPU consciousness is NOT in the LOINC map and units
are NOT normalized/converted — both assertions below document that baseline.
"""

import pytest

from src.core.ingestion.fhir_parser import LOINC_CODES, parse_batch, parse_observation

pytestmark = pytest.mark.unit


def _obs(loinc: str, value, patient_id: str = "PT-001", unit: str = "bpm",
         effective: str = "2026-07-02T08:00:00Z", value_string=None,
         resource_type: str = "Observation"):
    """Build a minimal FHIR R4 Observation dict."""
    code = {"system": "http://loinc.org", "code": loinc, "display": "Test"}
    obj = {
        "resourceType": resource_type,
        "subject": {"reference": f"Patient/{patient_id}"},
        "code": {"coding": [code]},
    }
    if value_string is not None:
        obj["valueString"] = value_string
    else:
        obj["valueQuantity"] = {"value": value, "unit": unit}
    if effective is not None:
        obj["effectiveDateTime"] = effective
    return obj


class TestLoincMapping:
    def test_all_supported_loinc_codes_present(self):
        # Baseline supports exactly these 6 LOINC codes (AVPU is NOT present — see Baseline).
        for loinc in LOINC_CODES:
            assert loinc

    def test_supported_loinc_to_vital_type(self):
        assert LOINC_CODES["8867-4"] == "heart_rate"
        assert LOINC_CODES["8480-6"] == "systolic_bp"
        assert LOINC_CODES["8462-4"] == "diastolic_bp"
        assert LOINC_CODES["2708-6"] == "spo2"
        assert LOINC_CODES["9279-1"] == "respiratory_rate"
        assert LOINC_CODES["8310-5"] == "temperature"

    def test_no_avpu_loinc_in_baseline(self):
        # Legacy limitation: consciousness (AVPU) is not mapped to any LOINC.
        avpu_loincs = {"11045-6", "35088-4", "9275-6"}
        assert not (avpu_loincs & set(LOINC_CODES))


class TestParseObservation:
    def test_parses_each_supported_vital(self):
        cases = [
            ("8867-4", 72, "heart_rate"),
            ("8480-6", 120, "systolic_bp"),
            ("8462-4", 80, "diastolic_bp"),
            ("2708-6", 98, "spo2"),
            ("9279-1", 16, "respiratory_rate"),
            ("8310-5", 36.5, "temperature"),
        ]
        for loinc, value, vital_type in cases:
            parsed = parse_observation(_obs(loinc, value))
            assert parsed["vital_type"] == vital_type
            assert parsed["value"] == value
            assert parsed["patient_id"] == "PT-001"
            assert parsed["unit"] == "bpm"
            assert parsed["timestamp"] == "2026-07-02T08:00:00Z"

    def test_patient_reference_stripped(self):
        parsed = parse_observation(_obs("8867-4", 72, patient_id="P-123"))
        assert parsed["patient_id"] == "P-123"

    def test_missing_subject_reference_defaults_unknown(self):
        obj = _obs("8867-4", 72)
        obj.pop("subject")
        assert parse_observation(obj)["patient_id"] == "unknown"

    def test_unknown_loinc_returns_empty(self):
        parsed = parse_observation(_obs("9999-9", 100))
        assert parsed == {}

    def test_missing_loinc_returns_empty(self):
        obj = _obs("8867-4", 72)
        obj["code"] = {"coding": [{"system": "http://loinc.org"}]}
        assert parse_observation(obj) == {}

    def test_wrong_resource_type_raises(self):
        with pytest.raises(ValueError, match="Expected Observation"):
            parse_observation(_obs("8867-4", 72, resource_type="Patient"))

    def test_missing_value_quantity_yields_none_value(self):
        obj = _obs("8867-4", 72)
        obj.pop("valueQuantity")
        parsed = parse_observation(obj)
        assert parsed["vital_type"] == "heart_rate"
        assert parsed["value"] is None

    def test_value_string_fallback(self):
        parsed = parse_observation(_obs("8867-4", None, value_string="72"))
        assert parsed["value"] == "72"

    def test_effective_date_time_takes_precedence(self):
        parsed = parse_observation(_obs("8867-4", 72, effective="2026-07-02T09:30:00Z"))
        assert parsed["timestamp"] == "2026-07-02T09:30:00Z"

    def test_falls_back_to_issued(self):
        obj = _obs("8867-4", 72, effective=None)
        obj["issued"] = "2026-07-02T10:00:00Z"
        assert parse_observation(obj)["timestamp"] == "2026-07-02T10:00:00Z"


class TestParseBatch:
    def test_valid_entries_returned(self):
        batch = [_obs("8867-4", 72), _obs("8480-6", 120)]
        results = parse_batch(batch)
        assert len(results) == 2
        assert {r["vital_type"] for r in results} == {"heart_rate", "systolic_bp"}

    def test_unknown_loinc_skipped(self):
        results = parse_batch([_obs("9999-9", 100), _obs("8867-4", 72)])
        assert len(results) == 1
        assert results[0]["vital_type"] == "heart_rate"

    def test_malformed_entries_skipped(self):
        # Non-dict entries and malformed dicts are skipped without crashing.
        results = parse_batch([
            "not-a-dict",
            None,
            12345,
            {"code": {"coding": []}},
            _obs("8867-4", 72),
            {},
        ])
        assert len(results) == 1
        assert results[0]["vital_type"] == "heart_rate"

    def test_empty_batch_returns_empty(self):
        assert parse_batch([]) == []


class TestUnitHandling:
    def test_unit_preserved_as_is(self):
        # Baseline limitation: NO unit normalization. Unit string is stored verbatim.
        parsed = parse_observation(_obs("8867-4", 72, unit="beats per minute"))
        assert parsed["unit"] == "beats per minute"

    def test_non_standard_unit_not_converted(self):
        # Baseline limitation: °F is not converted to °C; stored verbatim.
        parsed = parse_observation(_obs("8310-5", 98.6, unit="degF"))
        assert parsed["unit"] == "degF"
        assert parsed["value"] == 98.6
