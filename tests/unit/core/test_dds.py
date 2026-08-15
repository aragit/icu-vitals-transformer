"""Unit tests for the Core Deterministic Deterioration Score (DDS).

Covers Phase 1 AVPU scoring: an AVPU value other than ``A`` (Alert) now
propagates through the windowing engine and adds a +3
``altered_consciousness_*`` factor to the DDS, closing the Phase 0
"AVPU windowing loss" gap (docs/BASELINE.md §5.2).
"""

from __future__ import annotations

import pytest

from src.core.domain.vitals import VitalSignsWindow
from src.core.governance.deterioration import DDS_MAX_SCORE, compute_dds
from src.core.windowing.engine import window_vitals

pytestmark = pytest.mark.unit

ISO0 = "2026-07-02T08:00:00Z"
ISO_PLUS1 = "2026-07-02T08:01:00Z"
_ISO0 = "2026-07-02T08:00:00"


def _window(**kw) -> VitalSignsWindow:
    defaults = {
        "patient_id": "PT-001",
        "window_start": _ISO0,
        "window_end": _ISO0,
    }
    defaults.update(kw)
    return VitalSignsWindow(**defaults)


class TestAvpuScoring:
    @pytest.mark.parametrize("avpu", ["V", "P", "U"])
    def test_non_alert_avpu_adds_three(self, avpu: str) -> None:
        w = _window(heart_rate=70, systolic_bp=120, avpu=avpu)
        score, factors = compute_dds(w)
        assert f"altered_consciousness_{avpu}" in factors
        assert score == 3

    def test_alert_avpu_no_penalty(self) -> None:
        w = _window(heart_rate=70, systolic_bp=120, avpu="A")
        score, factors = compute_dds(w)
        assert not any(f.startswith("altered_consciousness") for f in factors)
        assert score == 0

    def test_null_avpu_no_penalty(self) -> None:
        w = _window(heart_rate=70, systolic_bp=120, avpu=None)
        score, factors = compute_dds(w)
        assert not any(f.startswith("altered_consciousness") for f in factors)
        assert score == 0

    def test_avpu_cap_at_max(self) -> None:
        # With every vital critical and AVPU=Unresponsive, the DDS reaches its
        # realistic maximum (resp+spo2+sbp+hr+temp+avpu = 3*5 + 2 = 17) and is
        # still bounded by DDS_MAX_SCORE (20). AVPU contributes the +3 that
        # pushes the score to the cap, not beyond it.
        w = _window(
            heart_rate=200,
            systolic_bp=250,
            spo2=80,
            respiratory_rate=30,
            temperature=40,
            avpu="U",
        )
        score, factors = compute_dds(w)
        assert "altered_consciousness_U" in factors
        assert score == 17.0
        assert score <= float(DDS_MAX_SCORE)


class TestEndToEndAvpuWindowingToDds:
    """The Phase 1 fix: avpu in source records reaches DDS via windowing."""

    def test_windowed_avpu_drives_dds(self) -> None:
        records = [
            {"patient_id": "PT-001", "vital_type": "heart_rate",
             "value": 70, "timestamp": ISO0, "unit": "bpm", "avpu": "V"},
            {"patient_id": "PT-001", "vital_type": "heart_rate",
             "value": 74, "timestamp": ISO_PLUS1, "unit": "bpm", "avpu": "P"},
        ]
        window = window_vitals(records, "PT-001")
        assert window is not None
        assert window.avpu == "P"
        score, factors = compute_dds(window)
        assert "altered_consciousness_P" in factors
        assert score == 3


class TestSeverityTiers:
    """Task 3.1: DDS severity tiers must match src/core/governance/severity.py
    (NORMAL 0-2, WARNING 3-4, ALERT 5-6, EMERGENCY >=7) and the manifests."""

    @pytest.mark.parametrize(
        "score, expected",
        [
            (0, "NORMAL"),
            (2, "NORMAL"),
            (3, "WARNING"),
            (4, "WARNING"),
            (5, "ALERT"),
            (6, "ALERT"),
            (7, "EMERGENCY"),
            (20, "EMERGENCY"),
        ],
    )
    def test_tier_boundaries(self, score: int, expected: str) -> None:
        from src.core.governance.severity import severity_from_score

        assert severity_from_score(float(score)) == expected


class TestEndToEndAvpuValueCodeableConcept:
    """Task 1.3: AVPU coded as a FHIR R4 valueCodeableConcept (SNOMED CT) reaches
    the DDS scoring path through the full parse -> window -> compute pipeline."""

    def test_snomed_consciousness_flows_to_dds(self) -> None:
        from src.core.ingestion.fhir_parser import parse_observation

        # SNOMED CT 450847001 = Responds to Pain -> "P".
        observation = {
            "resourceType": "Observation",
            "subject": {"reference": "Patient/PT-001"},
            "code": {"coding": [{"system": "http://loinc.org", "code": "8867-4"}]},
            "valueCodeableConcept": {
                "coding": [{"system": "http://snomed.info/sct", "code": "450847001"}]
            },
            "effectiveDateTime": ISO0,
        }
        parsed = parse_observation(observation)
        assert parsed["avpu"] == "P"
        window = window_vitals([parsed], "PT-001")
        assert window is not None
        assert window.avpu == "P"
        score, factors = compute_dds(window)
        assert "altered_consciousness_P" in factors
        assert score == 3
