"""Unit tests for sliding-window aggregation (baseline contract).

Pin the baseline behavior of ``src.core.ingestion.windowing.window_vitals``,
including legacy limitations documented in docs/BASELINE.md §5.2 & §6:
the window is anchored on the OLDEST record, records are sorted by
lexicographic string timestamp, and AVPU is never populated.
"""

from datetime import datetime, timedelta

import pytest

from src.core.domain.vitals import VitalSignsWindow
from src.core.windowing.engine import window_vitals

pytestmark = pytest.mark.unit


def _rec(vt: str, value, ts: str, patient_id: str = "PT-001", unit: str = "bpm"):
    return {
        "patient_id": patient_id,
        "vital_type": vt,
        "value": value,
        "timestamp": ts,
        "unit": unit,
    }


ISO0 = "2026-07-02T08:00:00Z"
ISO_PLUS1 = "2026-07-02T08:01:00Z"
ISO_PLUS2 = "2026-07-02T08:02:00Z"
ISO_PLUS10 = "2026-07-02T08:10:00Z"


class TestEmptyAndFiltering:
    def test_empty_batch_returns_none(self):
        assert window_vitals([], "PT-001", anchor="oldest") is None

    def test_no_records_for_patient_returns_none(self):
        records = [_rec("heart_rate", 70, ISO0, patient_id="PT-002")]
        assert window_vitals(records, "PT-001", anchor="oldest") is None

    def test_patient_records_filtered_by_id_only(self):
        records = [
            _rec("heart_rate", 70, ISO0, patient_id="PT-001"),
            _rec("heart_rate", 90, ISO0, patient_id="PT-002"),
        ]
        window = window_vitals(records, "PT-001", window_minutes=10, anchor="oldest")
        assert window.heart_rate == 70.0


class TestSingleObservation:
    def test_single_record_becomes_window(self):
        records = [_rec("heart_rate", 72, ISO0)]
        window = window_vitals(records, "PT-001", anchor="oldest")
        assert window is not None
        assert window.patient_id == "PT-001"
        assert window.heart_rate == 72.0
        assert window.systolic_bp is None
        # Window is anchored on the single (oldest) record + 5 minutes.
        assert window.window_start == datetime.fromisoformat(ISO0.replace("Z", "+00:00"))
        assert window.window_end == window.window_start + timedelta(minutes=5)


class TestChronology:
    def test_out_of_order_sorted_chronologically(self):
        # Given out of order; baseline sorts lexicographically (ISO-UTC safe).
        records = [
            _rec("heart_rate", 80, ISO_PLUS2),
            _rec("heart_rate", 70, ISO0),
            _rec("heart_rate", 74, ISO_PLUS1),
        ]
        window = window_vitals(records, "PT-001", window_minutes=5, anchor="oldest")
        # Oldest anchor = ISO0; all three within 5 min window.
        assert window.heart_rate == round((70 + 74 + 80) / 3, 2)
        assert window.window_start == datetime.fromisoformat(ISO0.replace("Z", "+00:00"))

    def test_records_outside_window_excluded(self):
        # ISO_PLUS10 is beyond a 5-minute window anchored at ISO0.
        records = [
            _rec("heart_rate", 70, ISO0),
            _rec("heart_rate", 80, ISO_PLUS10),
        ]
        window = window_vitals(records, "PT-001", window_minutes=5, anchor="oldest")
        assert window.heart_rate == 70.0

    def test_window_anchored_on_oldest(self):
        # Legacy limitation: anchor is the OLDEST record, not the newest.
        records = [
            _rec("heart_rate", 90, ISO_PLUS2),
            _rec("heart_rate", 70, ISO0),
        ]
        window = window_vitals(records, "PT-001", window_minutes=5, anchor="oldest")
        assert window.window_start == datetime.fromisoformat(ISO0.replace("Z", "+00:00"))
        assert window.heart_rate == round((90 + 70) / 2, 2)


class TestAggregation:
    def test_mean_aggregation(self):
        records = [
            _rec("heart_rate", 70, ISO0),
            _rec("heart_rate", 74, ISO_PLUS1),
            _rec("systolic_bp", 120, ISO0),
        ]
        window = window_vitals(records, "PT-001", window_minutes=5, anchor="oldest")
        assert window.heart_rate == 72.0
        assert window.systolic_bp == 120.0
        assert window.spo2 is None

    def test_non_numeric_values_skipped(self):
        records = [
            _rec("heart_rate", "invalid", ISO0),
            _rec("heart_rate", 80, ISO_PLUS1),
        ]
        window = window_vitals(records, "PT-001", window_minutes=5, anchor="oldest")
        assert window.heart_rate == 80.0

    def test_null_values_skipped(self):
        records = [
            _rec("heart_rate", None, ISO0),
            _rec("heart_rate", 80, ISO_PLUS1),
        ]
        window = window_vitals(records, "PT-001", window_minutes=5, anchor="oldest")
        assert window.heart_rate == 80.0

    def test_numeric_string_values_coerced(self):
        records = [_rec("heart_rate", "72", ISO0)]
        window = window_vitals(records, "PT-001", window_minutes=5, anchor="oldest")
        assert window.heart_rate == 72.0


class TestAvpuLimitation:
    def test_avpu_always_none_in_window(self):
        # Legacy limitation (#6): no AVPU LOINC is mapped, so the window's avpu
        # can never be populated by the pipeline.
        records = [_rec("heart_rate", 72, ISO0)]
        window = window_vitals(records, "PT-001", anchor="oldest")
        assert isinstance(window, VitalSignsWindow)
        assert window.avpu is None

    def test_avpu_record_ignored_by_pipeline(self):
        # Even a record that looks like it carries an avpu vital_type is
        # dropped from aggregation (avpu not in the values map).
        records = [_rec("avpu", "V", ISO0, unit=None)]
        window = window_vitals(records, "PT-001", window_minutes=5, anchor="oldest")
        assert window.avpu is None
