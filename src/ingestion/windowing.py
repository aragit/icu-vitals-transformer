"""Sliding window aggregation for vital signs."""

from datetime import datetime, timedelta
from typing import Optional

from loguru import logger

from src.models.vitals import VitalSignsWindow


def window_vitals(
    parsed_records: list[dict],
    patient_id: str,
    window_minutes: int = 5,
) -> Optional[VitalSignsWindow]:
    """Aggregate parsed vital records into a single VitalSignsWindow."""
    if not parsed_records:
        return None

    # Filter by patient and sort by timestamp
    patient_records = [r for r in parsed_records if r.get("patient_id") == patient_id]
    if not patient_records:
        return None

    patient_records.sort(key=lambda x: x.get("timestamp", ""))

    # Define window from oldest to oldest + window_minutes
    window_start = datetime.fromisoformat(patient_records[0]["timestamp"].replace("Z", "+00:00"))
    window_end = window_start + timedelta(minutes=window_minutes)

    # Collect values by type within window
    values = {
        "heart_rate": [],
        "systolic_bp": [],
        "diastolic_bp": [],
        "spo2": [],
        "respiratory_rate": [],
        "temperature": [],
    }

    for record in patient_records:
        ts = datetime.fromisoformat(record["timestamp"].replace("Z", "+00:00"))
        if ts > window_end:
            break
        vital_type = record.get("vital_type")
        val = record.get("value")
        if vital_type in values and val is not None:
            try:
                values[vital_type].append(float(val))
            except (ValueError, TypeError):
                logger.warning(f"Non-numeric value for {vital_type}: {val}")

    # Aggregate: mean for continuous, last for AVPU (not handled here)
    def _mean(vals: list[float]) -> Optional[float]:
        return round(sum(vals) / len(vals), 2) if vals else None

    window = VitalSignsWindow(
        patient_id=patient_id,
        window_start=window_start,
        window_end=window_end,
        heart_rate=_mean(values["heart_rate"]),
        systolic_bp=_mean(values["systolic_bp"]),
        diastolic_bp=_mean(values["diastolic_bp"]),
        spo2=_mean(values["spo2"]),
        respiratory_rate=_mean(values["respiratory_rate"]),
        temperature=_mean(values["temperature"]),
    )

    logger.debug(f"Windowed vitals for {patient_id}: {window.model_dump()}")
    return window
