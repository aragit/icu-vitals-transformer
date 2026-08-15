"""Pure Pydantic v2 core domain models for vital signs.

These are the canonical, framework-agnostic data contracts for the ICU
vitals domain. They intentionally carry no FastAPI (``Field``-schema)
annotations specific to HTTP so they remain pure-domain (Core Isolation
invariant: no fastapi/mcp/prometheus imports).

Clinical bounds are intentionally NOT enforced as ``Field`` validators here:
a next-generation/neural backend may legitimately emit out-of-bound
projections (e.g. heart_rate=350) which ``SafetyShell`` clamp-then-log must
observe and correct rather than reject with a ``ValidationError``. Hard input
bounds live only in adapter-layer request schemas (FastAPI query/body models in
``src/adapters/rest/``); the domain model stays a permissive, pure-data
contract.
"""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel


class Observation(BaseModel):
    """A single parsed FHIR observation, normalized to internal form."""

    patient_id: str
    vital_type: str
    value: Optional[float] = None
    timestamp: str
    unit: Optional[str] = None


class VitalSignsWindow(BaseModel):
    """Aggregated vital signs over a time window."""

    patient_id: str
    window_start: datetime
    window_end: datetime

    heart_rate: Optional[float] = None
    systolic_bp: Optional[float] = None
    diastolic_bp: Optional[float] = None
    spo2: Optional[float] = None
    respiratory_rate: Optional[float] = None
    temperature: Optional[float] = None
    avpu: Optional[str] = None


class VitalIngestionRequest(BaseModel):
    """Batch FHIR Observation ingestion request."""

    observations: list[dict[str, Any]]
