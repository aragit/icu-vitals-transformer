"""Shared FHIR observation factories for Phase 5 E2E tests."""
from __future__ import annotations


def make_fhir_obs(
    loinc: str,
    value: float,
    patient_id: str = "PT-001",
    effective: str = "2026-07-02T08:00:00Z",
) -> dict:
    """Build a minimal FHIR R4 Observation for a single LOINC vital."""
    return {
        "resourceType": "Observation",
        "subject": {"reference": f"Patient/{patient_id}"},
        "code": {
            "coding": [
                {"system": "http://loinc.org", "code": loinc, "display": "Test"}
            ]
        },
        "valueQuantity": {"value": value, "unit": "bpm"},
        "effectiveDateTime": effective,
    }
