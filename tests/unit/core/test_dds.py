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
