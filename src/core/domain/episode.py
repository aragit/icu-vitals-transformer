"""Core domain episode model and state enum."""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class EpisodeState(str, Enum):
    """Risk tiers tracked per patient episode.

    Baseline mapping (Phase 1) — see docs/BASELINE.md §5.5. The legacy
    severity tiers NORMAL/WARNING/ALERT/EMERGENCY are surfaced here and the
    CRITICAL tier represents the post-refactor risk ceiling.
    """

    NORMAL = "NORMAL"
    WARNING = "WARNING"
    ALERT = "ALERT"
    EMERGENCY = "EMERGENCY"
    CRITICAL = "CRITICAL"


class Episode(BaseModel):
    """A tracked clinical episode for a single patient."""

    episode_id: str
    patient_id: str
    state: EpisodeState = Field(default=EpisodeState.NORMAL)
    available_vitals: set[str] = Field(default_factory=set)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
