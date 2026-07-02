"""MCP tool schema definitions."""

from pydantic import BaseModel, Field


class IngestVitalsInput(BaseModel):
    """Input schema for MCP tool: ingest_vitals."""

    patient_id: str = Field(..., description="Patient identifier")
    observations: list[dict] = Field(..., description="FHIR R4 Observation resources")


class GetForecastInput(BaseModel):
    """Input schema for MCP tool: get_forecast."""

    patient_id: str = Field(..., description="Patient identifier")
    horizon_minutes: int = Field(60, ge=60, le=720, description="Forecast horizon in minutes")


class GetDeteriorationInput(BaseModel):
    """Input schema for MCP tool: get_deterioration_index."""

    patient_id: str = Field(..., description="Patient identifier")
