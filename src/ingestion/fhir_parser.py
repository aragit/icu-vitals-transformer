"""Legacy FHIR ingestion shim — delegates to the Core domain parser.

Phase 1 strangler-fig: the canonical pure parser lives in
``src/core/ingestion/fhir_parser.py``. This thin adapter preserves the legacy
public API (``LOINC_CODES``, ``parse_observation``, ``parse_batch``) and
re-asserts the Phase 0 observability contract (``VITALS_INGESTED`` counter),
which the pure core layer intentionally does not own.
"""

from __future__ import annotations

from typing import Any

from src.core.ingestion.fhir_parser import (
    LOINC_CODES,
    parse_batch as _core_parse_batch,
    parse_observation as _core_parse_observation,
)
from src.observability.metrics import VITALS_INGESTED

__all__ = ["LOINC_CODES", "parse_observation", "parse_batch"]


def parse_observation(obs: dict[str, Any]) -> dict[str, Any]:
    return _core_parse_observation(obs)


def parse_batch(observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results = _core_parse_batch(observations)
    VITALS_INGESTED.inc(len(results))
    return results
