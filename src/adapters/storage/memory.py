"""In-Memory bounded repositories (driven storage adapters).

SINGLE-INSTANCE ONLY. For dev/test or single-replica deployments. Production
multi-replica deployments MUST use the Redis adapter (or another networked
adapter implementing the ``src.ports.repository`` Protocols); these in-process
deques do NOT replicate across replicas and will lose state on restart /
horizontal scale-out.

These repositories intentionally do **not** use ``asyncio.Lock()``. CPython's GIL
keeps dict/deque/set mutations atomic at the bytecode level, and asyncio's
single-threaded event loop already serialises coroutine execution; a lock here
is pure overhead with no race to guard. The methods remain ``async`` to satisfy
the ``Repository`` Protocol contracts.
"""

from __future__ import annotations

import uuid
from collections import deque
from datetime import datetime

from src.core.domain.episode import Episode
from src.core.domain.forecast import DeteriorationAssessment
from src.core.domain.vitals import VitalSignsWindow
from src.ports.repository import (
    AssessmentRepository,
    EpisodeRepository,
    VitalsRepository,
)

MAX_WINDOWS_PER_PATIENT: int = 1000
MAX_AUDIT_ENTRIES: int = 10000


class InMemoryVitalsRepository(VitalsRepository):
    """Per-patient sliding window store backed by bounded deques."""

    def __init__(self, maxlen: int = MAX_WINDOWS_PER_PATIENT) -> None:
        self._maxlen = maxlen
        self._store: dict[str, deque[VitalSignsWindow]] = {}

    async def append(self, patient_id: str, window: VitalSignsWindow) -> None:
        if patient_id not in self._store:
            self._store[patient_id] = deque(maxlen=self._maxlen)
        self._store[patient_id].append(window)

    async def get_window(self, patient_id: str) -> VitalSignsWindow | None:
        windows = self._store.get(patient_id)
        if not windows:
            return None
        return windows[-1]

    async def get_history(self, patient_id: str) -> list[VitalSignsWindow]:
        windows = self._store.get(patient_id)
        if windows is None:
            return []
        return list(windows)

    async def clear_old(self, patient_id: str) -> int:
        windows = self._store.pop(patient_id, None)
        if not windows:
            return 0
        return len(windows)


class InMemoryEpisodeRepository(EpisodeRepository):
    """Primary episode state (``dict``) with an active-patient index.

    Also maintains a secondary ``dict[str, VitalSignsWindow]`` so
    ``update_window`` can record the latest window against an episode without
    growing unbounded.
    """

    def __init__(self) -> None:
        self._episodes: dict[str, Episode] = {}
        self._active_by_patient: dict[str, set[str]] = {}
        self._windows: dict[str, VitalSignsWindow] = {}

    async def create(self, patient_id: str) -> Episode:
        episode_id = f"E-{uuid.uuid4().hex[:12]}"
        episode = Episode(episode_id=episode_id, patient_id=patient_id)
        self._episodes[episode.episode_id] = episode
        self._active_by_patient.setdefault(patient_id, set()).add(episode.episode_id)
        return episode

    async def get(self, episode_id: str) -> Episode | None:
        return self._episodes.get(episode_id)

    async def get_active_by_patient(self, patient_id: str) -> Episode | None:
        """Return the most recent active episode for a patient (by created_at)."""
        episode_ids = self._active_by_patient.get(patient_id)
        if not episode_ids:
            return None
        episodes = [
            self._episodes[eid] for eid in episode_ids if eid in self._episodes
        ]
        if not episodes:
            return None
        return max(episodes, key=lambda ep: ep.created_at)

    async def get_all_active_by_patient(self, patient_id: str) -> list[Episode]:
        """Return all currently-active episodes for a patient, newest first."""
        episode_ids = self._active_by_patient.get(patient_id)
        if not episode_ids:
            return []
        episodes = [
            self._episodes[eid] for eid in episode_ids if eid in self._episodes
        ]
        return sorted(episodes, key=lambda ep: ep.created_at, reverse=True)

    async def update(self, episode: Episode) -> Episode:
        """Persist a metadata update for an episode (e.g. available_vitals)."""
        self._episodes[episode.episode_id] = episode
        return episode

    async def update_window(self, episode_id: str, window: VitalSignsWindow) -> Episode:
        episode = self._episodes.get(episode_id)
        if episode is None:
            raise KeyError(f"Unknown episode: {episode_id}")
        self._windows[episode_id] = window
        available = {
            f for f in (
                "heart_rate", "systolic_bp", "diastolic_bp", "spo2",
                "respiratory_rate", "temperature",
            ) if getattr(window, f) is not None
        }
        if window.avpu is not None:
            available.add("avpu")
        episode.available_vitals = available
        episode.updated_at = datetime.utcnow()
        return episode


class InMemoryAssessmentRepository(AssessmentRepository):
    """Append-only audit log bounded by ``MAX_AUDIT_ENTRIES``."""

    def __init__(self, maxlen: int = MAX_AUDIT_ENTRIES) -> None:
        self._maxlen = maxlen
        self._audit: dict[str, deque[DeteriorationAssessment]] = {}

    async def append_assessment(
        self,
        episode_id: str,
        assessment: DeteriorationAssessment,
    ) -> None:
        if episode_id not in self._audit:
            self._audit[episode_id] = deque(maxlen=self._maxlen)
        self._audit[episode_id].append(assessment)

    async def get_audit_trail(self, episode_id: str) -> list[DeteriorationAssessment]:
        return list(self._audit.get(episode_id, []))


__all__ = [
    "InMemoryVitalsRepository",
    "InMemoryEpisodeRepository",
    "InMemoryAssessmentRepository",
    "MAX_AUDIT_ENTRIES",
    "MAX_WINDOWS_PER_PATIENT",
]
