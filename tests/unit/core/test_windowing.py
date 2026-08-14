"""Unit tests for the Core windowing engine.

Covers Phase 1 behavior: the sliding window is anchored on the most-recent
observation and **retains AVPU consciousness** from the most-recent record
within the window (Phase 0 dropped AVPU — see docs/BASELINE.md §5.2).
"""

from __future__ import annotations

import pytest

from src.core.windowing.engine import window_vitals

pytestmark = pytest.mark.unit

ISO0 = "2026-07-02T08:00:00Z"
ISO_PLUS1 = "2026-07-02T08:01:00Z"
ISO_PLUS2 = "2026-07-02T08:02:00Z"
ISO_PLUS10 = "2026-07-02T08:10:00Z"


def _rec(
    vital_type: str,
    value,
    ts: str,
    patient_id: str = "PT-001",
    unit: str = "bpm",
    avpu=None,
) -> dict:
    rec: dict = {
        "patient_id": patient_id,
        "vital_type": vital_type,
        "value": value,
        "timestamp": ts,
        "unit": unit,
    }
    if avpu is not None:
        rec["avpu"] = avpu
    return rec


class TestEmptyAndFiltering:
    def test_empty_batch_returns_none(self) -> None:
        assert window_vitals([], "PT-001") is None

    def test_no_records_for_patient_returns_none(self) -> None:
        records = [_rec("heart_rate", 70, ISO0, patient_id="PT-002")]
        assert window_vitals(records, "PT-001") is None

    def test_patient_records_filtered_by_id_only(self) -> None:
        records = [
            _rec("heart_rate", 70, ISO0, patient_id="PT-001"),
            _rec("heart_rate", 90, ISO0, patient_id="PT-002"),
        ]
        window = window_vitals(records, "PT-001", window_minutes=10)
        assert window is not None
        assert window.heart_rate == 70.0


class TestAvpuPropagation:
    def test_no_avpu_yields_none(self) -> None:
        records = [_rec("heart_rate", 72, ISO0)]
        window = window_vitals(records, "PT-001")
        assert window is not None
        assert window.avpu is None

    def test_single_avpu_propagated(self) -> None:
        records = [_rec("heart_rate", 72, ISO0, avpu="P")]
        window = window_vitals(records, "PT-001")
        assert window is not None
        assert window.avpu == "P"

    def test_most_recent_non_null_avpu_wins(self) -> None:
        # Two records within the default 5-minute window; the later (most
        # recent) AVPU token must be retained.
        records = [
            _rec("heart_rate", 70, ISO0, avpu="V"),
            _rec("heart_rate", 74, ISO_PLUS1, avpu="P"),
        ]
        window = window_vitals(records, "PT-001")
        assert window is not None
        assert window.avpu == "P"

    def test_avpu_outside_window_not_captured(self) -> None:
        # Recent anchor: only records within the trailing 5-minute window count.
        # The stale AVPU at ISO0 falls before window_start and must be ignored.
        records = [
            _rec("heart_rate", 70, ISO0, avpu="P"),
            _rec("heart_rate", 80, ISO_PLUS10, avpu=None),
        ]
        window = window_vitals(records, "PT-001", window_minutes=5)
        assert window is not None
        assert window.avpu is None
        assert window.heart_rate == 80.0

    def test_most_recent_avpu_within_window(self) -> None:
        # Oldest record's AVPU is stale (outside the 5-min window); the
        # in-window AVPU is what the window retains.
        records = [
            _rec("heart_rate", 70, ISO0, avpu="V"),     # outside window
            _rec("heart_rate", 71, ISO_PLUS1, avpu="A"),  # outside window
            _rec("heart_rate", 72, ISO_PLUS2, avpu="U"),  # within window
        ]
        window = window_vitals(records, "PT-001", window_minutes=5)
        assert window is not None
        assert window.avpu == "U"

    def test_invalid_avpu_token_ignored(self) -> None:
        records = [_rec("heart_rate", 72, ISO0, avpu="X")]
        window = window_vitals(records, "PT-001")
        assert window is not None
        assert window.avpu is None

    def test_avpu_does_not_break_aggregation(self) -> None:
        records = [
            _rec("heart_rate", 70, ISO0, avpu="P"),
            _rec("heart_rate", 80, ISO_PLUS1, avpu="P"),
            _rec("heart_rate", 90, ISO_PLUS2, avpu="P"),
        ]
        window = window_vitals(records, "PT-001")
        assert window is not None
        assert window.avpu == "P"
        assert window.heart_rate == 80.0
