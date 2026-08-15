"""Core domain episode model."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class Episode(BaseModel):
    """A tracked clinical episode for a single patient.

    An episode is a temporal monitoring container (created via
    ``POST /v2/patients/{id}/episodes`` or implicitly by ingest). Severity is
    **not** a property of the episode — it lives on ``DeteriorationAssessment``
    (computed by `compute_dds` + `severity_from_score`), so episodes carry no
    risk-tier state machine.
    """

    episode_id: str
    patient_id: str
    available_vitals: set[str] = Field(default_factory=set)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
