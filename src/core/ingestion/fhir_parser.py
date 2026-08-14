"""Pure FHIR R4 Observation parser (Core domain ingestion).

Core Isolation invariant: no imports from fastapi/mcp/prometheus_client/
redis/numpy. Uses only stdlib ``logging`` for diagnostics; metric counters
(and their prometheus dependency) live in the legacy adapter layer.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

LOINC_CODES: dict[str, str] = {
    "8867-4": "heart_rate",
    "8480-6": "systolic_bp",
    "8462-4": "diastolic_bp",
    "2708-6": "spo2",
    "9279-1": "respiratory_rate",
    "8310-5": "temperature",
}


def parse_observation(obs: dict[str, Any]) -> dict[str, Any]:
    """Parse a single FHIR R4 Observation into an internal record.

    Returns an empty dict when the resource is not an Observation or its
    LOINC code is unknown/missing (baseline contract — see docs/BASELINE.md).
    """
    if obs.get("resourceType") != "Observation":
        raise ValueError(f"Expected Observation, got {obs.get('resourceType')}")

    patient_ref = obs.get("subject", {}).get("reference", "")
    patient_id = patient_ref.replace("Patient/", "") if patient_ref else "unknown"

    code_coding = obs.get("code", {}).get("coding", [])
    loinc = next(
        (
            c.get("code")
            for c in code_coding
            if str(c.get("system", "")).endswith("loinc.org")
        ),
        None,
    )

    if not loinc or loinc not in LOINC_CODES:
        logger.warning("Unknown or missing LOINC code in observation: %s", loinc)
        return {}

    vital_type = LOINC_CODES[loinc]
    value: Any = None
    if "valueQuantity" in obs:
        value = obs["valueQuantity"].get("value")
    elif "valueString" in obs:
        value = obs["valueString"]

    effective = (
        obs.get("effectiveDateTime") or obs.get("issued")
        or datetime.utcnow().isoformat()
    )

    return {
        "patient_id": patient_id,
        "vital_type": vital_type,
        "value": value,
        "timestamp": effective,
        "unit": obs.get("valueQuantity", {}).get("unit"),
    }


def parse_batch(observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Parse a batch of FHIR Observations, skipping invalid entries."""
    results: list[dict[str, Any]] = []
    for obs in observations:
        try:
            parsed = parse_observation(obs)
            if parsed:
                results.append(parsed)
        except Exception as exc:  # noqa: BLE001 - baseline matches legacy
            logger.warning("Failed to parse observation: %s", exc)
    return results
