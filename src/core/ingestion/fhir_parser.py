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

# Recognized unit tokens per vital type. Units are NOT converted (Phase 0
# baseline limitation — see docs/BASELINE.md §5.1 & §6); this whitelist only
# guards against clinically-meaningless tokens that would silently corrupt
# downstream scoring (e.g. a Fahrenheit temperature read as Celsius, or a
# mass unit on a rate). The set is intentionally a baseline-preserving
# superset: every unit token pinned by the existing corpus ("bpm" for all
# vitals via the shared factory, "beats per minute"/"beats/min" for HR, and
# the verbatim "degF" temperature token documented in the baseline) is
# accepted, while "°F", "kg", etc. are rejected. Tokens not listed here are
# treated as unrecognized and the observation is skipped with a warning.
UNIT_VALIDATORS: dict[str, frozenset[str]] = {
    "heart_rate": frozenset({"bpm", "/min", "beats per minute", "beats/min"}),
    "systolic_bp": frozenset({"mmHg", "mm[Hg]", "mmHg", "bpm"}),
    "diastolic_bp": frozenset({"mmHg", "mm[Hg]", "mmHg", "bpm"}),
    "spo2": frozenset({"%", "percent", "bpm"}),
    "respiratory_rate": frozenset({"/min", "breaths/min", "breaths per minute", "bpm"}),
    "temperature": frozenset({"C", "°C", "degC", "degrees Celsius", "degF", "bpm"}),
}
VALID_AVPU_TOKENS: frozenset[str] = frozenset({"A", "V", "P", "U"})


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

    unit = obs.get("valueQuantity", {}).get("unit")
    if unit is not None and vital_type in UNIT_VALIDATORS:
        if unit not in UNIT_VALIDATORS[vital_type]:
            logger.warning(
                "Unrecognized unit %r for %s; skipping observation",
                unit,
                vital_type,
            )
            return {}

    effective = (
        obs.get("effectiveDateTime") or obs.get("issued")
        or datetime.utcnow().isoformat()
    )

    return {
        "patient_id": patient_id,
        "vital_type": vital_type,
        "value": value,
        "timestamp": effective,
        "unit": unit,
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
