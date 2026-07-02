"""Forecast and governance output models."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from .vitals import VitalSignsWindow


class ForecastResult(BaseModel):
    """Multi-horizon forecast with uncertainty and governance classification."""

    patient_id: str
    horizon_minutes: int = Field(..., ge=60, le=720)
    forecasted_vitals: VitalSignsWindow
    uncertainty_lower: VitalSignsWindow
    uncertainty_upper: VitalSignsWindow
    deterioration_index: float = Field(..., ge=0, le=20)
    severity: str = Field(..., pattern=r"^(NORMAL|WARNING|ALERT|EMERGENCY)$")
    generated_at: datetime = Field(default_factory=datetime.utcnow)


class DeteriorationAssessment(BaseModel):
    """Deterministic governance output — severity classification only, no action."""

    patient_id: str
    ensemble_score: float = Field(..., ge=0, le=20)
    severity: str = Field(..., pattern=r"^(NORMAL|WARNING|ALERT|EMERGENCY)$")
    contributing_factors: list[str] = Field(default_factory=list)
    assessed_at: datetime = Field(default_factory=datetime.utcnow)
