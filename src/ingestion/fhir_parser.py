"""FHIR R4 Observation parser."""

from datetime import datetime
from typing import Optional

from loguru import logger


LOINC_CODES = {
    "8867-4": "heart_rate",
    "8480-6": "systolic_bp",
    "8462-4": "diastolic_bp",
    "2708-6": "spo2",
    "9279-1": "respiratory_rate",
    "8310-5": "temperature",
}


def parse_observation(obs: dict) -> dict:
    """Parse a single FHIR R4 Observation into internal vital sign record."""
    if obs.get("resourceType") != "Observation":
        raise ValueError(f"Expected Observation, got {obs.get('resourceType')}")

    patient_ref = obs.get("subject", {}).get("reference", "")
    patient_id = patient_ref.replace("Patient/", "") if patient_ref else "unknown"

    code_coding = obs.get("code", {}).get("coding", [])
    loinc = next((c.get("code") for c in code_coding if c.get("system", "").endswith("loinc.org")), None)

    if not loinc or loinc not in LOINC_CODES:
        logger.warning(f"Unknown or missing LOINC code in observation: {loinc}")
        return {}

    vital_type = LOINC_CODES[loinc]
    value = None

    if "valueQuantity" in obs:
        value = obs["valueQuantity"].get("value")
    elif "valueString" in obs:
        value = obs["valueString"]

    effective = obs.get("effectiveDateTime") or obs.get("issued") or datetime.utcnow().isoformat()

    return {
        "patient_id": patient_id,
        "vital_type": vital_type,
        "value": value,
        "timestamp": effective,
        "unit": obs.get("valueQuantity", {}).get("unit"),
    }


def parse_batch(observations: list[dict]) -> list[dict]:
    """Parse a batch of FHIR Observations, skip invalid entries."""
    results = []
    for obs in observations:
        try:
            parsed = parse_observation(obs)
            if parsed:
                results.append(parsed)
        except Exception as e:
            logger.warning(f"Failed to parse observation: {e}")
    return results
