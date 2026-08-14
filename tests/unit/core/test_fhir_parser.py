"""Unit tests for the Core FHIR R4 Observation parser.

Covers Phase 1 unit-validation behavior: clinically-meaningless units
(e.g. ``°F`` for a temperature, ``kg`` for a heart rate) are rejected, while
the verbatim unit tokens pinned by the baseline corpus stay accepted so the
legacy contract (docs/BASELINE.md §5.1 & §6) is not broken.
"""

from __future__ import annotations

import logging

import pytest

from src.core.ingestion.fhir_parser import (
    LOINC_CODES,
    UNIT_VALIDATORS,
    parse_batch,
    parse_observation,
)

pytestmark = pytest.mark.unit

ISO = "2026-07-02T08:00:00Z"


def _obs(loinc: str, value, unit: str = "bpm", patient_id: str = "PT-001"):
    """Build a minimal FHIR R4 Observation dict."""
    return {
        "resourceType": "Observation",
        "subject": {"reference": f"Patient/{patient_id}"},
        "code": {
            "coding": [{"system": "http://loinc.org", "code": loinc, "display": "T"}]
        },
        "valueQuantity": {"value": value, "unit": unit},
        "effectiveDateTime": ISO,
    }


class TestUnitValidation:
    """Per-vital unit whitelist rejects clinically-invalid tokens."""

    @pytest.mark.parametrize(
        "loinc,vital_type",
        [
            ("8867-4", "heart_rate"),
            ("8480-6", "systolic_bp"),
            ("8462-4", "diastolic_bp"),
            ("2708-6", "spo2"),
            ("9279-1", "respiratory_rate"),
            ("8310-5", "temperature"),
        ],
    )
    def test_valid_unit_parsed(self, loinc, vital_type) -> None:
        unit = next(iter(UNIT_VALIDATORS[vital_type]))
        parsed = parse_observation(_obs(loinc, 42, unit=unit))
        assert parsed["vital_type"] == vital_type
        assert parsed["unit"] == unit
        assert parsed["value"] == 42

    def test_temperature_fahrenheit_skipped(self) -> None:
        parsed = parse_observation(_obs("8310-5", 98.6, unit="°F"))
        assert parsed == {}

    def test_temperature_fahrenheit_lowercase_skipped(self) -> None:
        parsed = parse_observation(_obs("8310-5", 98.6, unit="F"))
        assert parsed == {}

    def test_heart_rate_with_mass_unit_skipped(self) -> None:
        parsed = parse_observation(_obs("8867-4", 72, unit="kg"))
        assert parsed == {}

    def test_spo2_with_mass_unit_skipped(self) -> None:
        parsed = parse_observation(_obs("2708-6", 98, unit="kg"))
        assert parsed == {}

    def test_unrecognized_unit_skipped_logs_warning(self, caplog) -> None:
        with caplog.at_level(logging.WARNING, logger="src.core.ingestion.fhir_parser"):
            parsed = parse_observation(_obs("8310-5", 98.6, unit="°F"))
        assert parsed == {}
        assert any("Unrecognized unit" in rec.message for rec in caplog.records)

    def test_unrecognized_unit_does_not_corrupt_value(self) -> None:
        parsed = parse_observation(_obs("8310-5", 98.6, unit="°F"))
        assert parsed == {}


class TestBaselineUnitCompatibility:
    """The Phase 0 baseline contract is preserved (no behavior regression)."""

    def test_bpm_accepted_for_every_vital(self) -> None:
        # Shared factory hardcodes "bpm" for all vitals; all must still parse.
        for loinc, vital_type in LOINC_CODES.items():
            parsed = parse_observation(_obs(loinc, 1, unit="bpm"))
            assert parsed["vital_type"] == vital_type
            assert parsed["unit"] == "bpm"

    def test_non_standard_unit_verbatim_token_still_parsed(self) -> None:
        # Baseline limitation preserved: "degF" is a documented verbatim token.
        parsed = parse_observation(_obs("8310-5", 98.6, unit="degF"))
        assert parsed["unit"] == "degF"
        assert parsed["value"] == 98.6

    def test_beats_per_minute_accepted_for_heart_rate(self) -> None:
        parsed = parse_observation(_obs("8867-4", 72, unit="beats per minute"))
        assert parsed["vital_type"] == "heart_rate"
        assert parsed["unit"] == "beats per minute"

    def test_slash_min_accepted_for_heart_rate(self) -> None:
        parsed = parse_observation(_obs("8867-4", 72, unit="beats/min"))
        assert parsed["vital_type"] == "heart_rate"
        assert parsed["unit"] == "beats/min"


class TestParseBatchWithValidation:
    def test_bad_unit_observation_skipped_in_batch(self) -> None:
        batch = [_obs("8867-4", 72, unit="bpm"), _obs("8310-5", 98.6, unit="°F")]
        results = parse_batch(batch)
        assert len(results) == 1
        assert results[0]["vital_type"] == "heart_rate"
