"""Pure Pydantic v2 core domain models for vital signs.

These are the canonical, framework-agnostic data contracts for the ICU
vitals domain. They intentionally carry no FastAPI (``Field``-schema)
annotations specific to HTTP so they remain pure-domain (Core Isolation
invariant: no fastapi/mcp/prometheus imports).
"""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


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

    heart_rate: Optional[float] = Field(None, ge=0, le=300)
    systolic_bp: Optional[float] = Field(None, ge=0, le=300)
    diastolic_bp: Optional[float] = Field(None, ge=0, le=200)
    spo2: Optional[float] = Field(None, ge=0, le=100)
    respiratory_rate: Optional[float] = Field(None, ge=0, le=60)
    temperature: Optional[float] = Field(None, ge=30, le=45)
    avpu: Optional[str] = Field(None, pattern=r"^[AVPU]$")


class VitalIngestionRequest(BaseModel):
    """Batch FHIR Observation ingestion request."""

    observations: list[dict[str, Any]]
