"""Core domain forecast and governance output models.

Pure Pydantic v2 contracts shared by the domain layer. ``ForecastResult``
gains two extra baseline-lock fields versus the legacy model:
``data_freshness_seconds`` and ``stale_data_warning``, consumed by the
``SafetyShell`` port (see docs/BASELINE.md for the contract baseline).
"""

from datetime import datetime

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
    data_freshness_seconds: int = 0
    stale_data_warning: bool = False
    contributing_factors: list[str] = Field(default_factory=list)


class DeteriorationAssessment(BaseModel):
    """Deterministic governance output — severity classification only."""

    patient_id: str
    dds_score: float = Field(..., ge=0, le=20)
    severity: str = Field(..., pattern=r"^(NORMAL|WARNING|ALERT|EMERGENCY)$")
    contributing_factors: list[str] = Field(default_factory=list)
    assessed_at: datetime = Field(default_factory=datetime.utcnow)
