"""Vital signs data models."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class VitalSignsWindow(BaseModel):
    """Aggregated vital signs over a time window."""

    patient_id: str = Field(..., description="Unique patient identifier")
    window_start: datetime = Field(..., description="Window start timestamp")
    window_end: datetime = Field(..., description="Window end timestamp")

    heart_rate: Optional[float] = Field(None, ge=0, le=300, description="Heart rate in bpm")
    systolic_bp: Optional[float] = Field(None, ge=0, le=300, description="Systolic BP in mmHg")
    diastolic_bp: Optional[float] = Field(None, ge=0, le=200, description="Diastolic BP in mmHg")
    spo2: Optional[float] = Field(None, ge=0, le=100, description="SpO2 percentage")
    respiratory_rate: Optional[float] = Field(None, ge=0, le=60, description="Respiratory rate /min")
    temperature: Optional[float] = Field(None, ge=30, le=45, description="Temperature in Celsius")
    avpu: Optional[str] = Field(None, pattern=r"^[AVPU]$", description="A=Alert, V=Voice, P=Pain, U=Unresponsive")


class VitalIngestionRequest(BaseModel):
    """Single or batch FHIR Observation ingestion request."""

    observations: list[dict] = Field(..., description="List of FHIR R4 Observation resources")
