"""Temporal windowing engine for vital signs (Core domain windowing).

Core Isolation invariant: pure Python + pydantic only.

Anchoring strategy (Phase 1 baseline — replaces the Phase 0 oldest-anchor):
windows are anchored on ``max(t_observations)`` (the most recent observation),
spanning ``window_minutes`` backwards. AVPU categorical status is retained
from the most-recent record carrying it.

The legacy ``src/ingestion/windowing.py`` shim invokes this with
``anchor="oldest"`` so the Phase 0 baseline tests (which pin oldest-anchor
behavior) keep passing during the strangler migration.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Optional

from src.core.domain.vitals import VitalSignsWindow
from src.core.ingestion.fhir_parser import VALID_AVPU_TOKENS

logger = logging.getLogger(__name__)

VITAL_TYPES: tuple[str, ...] = (
    "heart_rate",
    "systolic_bp",
    "diastolic_bp",
    "spo2",
    "respiratory_rate",
    "temperature",
)


def _parse_ts(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _mean(values: list[float]) -> Optional[float]:
    return round(sum(values) / len(values), 2) if values else None


def window_vitals(
    parsed_records: list[dict[str, Any]],
    patient_id: str,
    window_minutes: int = 5,
    anchor: str = "recent",
) -> Optional[VitalSignsWindow]:
    """Aggregate parsed vital records into a single ``VitalSignsWindow``.

    Args:
        parsed_records: normalized records from the FHIR parser.
        patient_id: only records for this patient are considered.
        window_minutes: window span.
        anchor: ``"recent"`` (default, Phase 1 — most-recent anchor) or
            ``"oldest"`` (Phase 0 legacy anchor, used by the shim).
    """
    if not parsed_records:
        return None

    patient_records = [
        r for r in parsed_records if r.get("patient_id") == patient_id
    ]
    if not patient_records:
        return None

    # Lexicographic sort is correct for ISO-8601 UTC strings (Phase 0 baseline).
    patient_records.sort(key=lambda x: str(x.get("timestamp", "")))

    anchor_idx = -1 if anchor == "recent" else 0
    anchor_ts = _parse_ts(str(patient_records[anchor_idx]["timestamp"]))

    if anchor == "recent":
        window_end = anchor_ts
        window_start = window_end - timedelta(minutes=window_minutes)
    else:  # oldest
        window_start = anchor_ts
        window_end = window_start + timedelta(minutes=window_minutes)

    values: dict[str, list[float]] = {vt: [] for vt in VITAL_TYPES}
    most_recent_avpu: Optional[str] = None
    for record in patient_records:
        ts = _parse_ts(str(record["timestamp"]))
        if anchor == "recent" and ts < window_start:
            continue
        if anchor == "oldest" and ts > window_end:
            break
        vital_type = record.get("vital_type")
        val = record.get("value")
        if vital_type in values and val is not None:
            try:
                values[vital_type].append(float(val))
            except (TypeError, ValueError):
                logger.warning("Non-numeric value for %s: %s", vital_type, val)
        avpu_candidate = record.get("avpu")
        if (
            isinstance(avpu_candidate, str)
            and avpu_candidate in VALID_AVPU_TOKENS
        ):
            most_recent_avpu = avpu_candidate

    return VitalSignsWindow(
        patient_id=patient_id,
        window_start=window_start,
        window_end=window_end,
        heart_rate=_mean(values["heart_rate"]),
        systolic_bp=_mean(values["systolic_bp"]),
        diastolic_bp=_mean(values["diastolic_bp"]),
        spo2=_mean(values["spo2"]),
        respiratory_rate=_mean(values["respiratory_rate"]),
        temperature=_mean(values["temperature"]),
        avpu=most_recent_avpu,
    )
