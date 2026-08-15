"""Core domain episode model and state enum."""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class EpisodeState(str, Enum):
    """Risk tiers tracked per patient episode.

    Automated DDS scoring emits NORMAL/WARNING/ALERT/EMERGENCY only.
    CRITICAL is reserved for a future manual clinician override and is never
    assigned by ``severity_from_score``; it remains in the enum so the episode
    lifecycle can represent a manually-declared ceiling without destabilising
    existing automated tiers.
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
