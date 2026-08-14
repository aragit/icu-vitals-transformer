"""In-Memory bounded repositories (driven storage adapters).

InMemoryBoundedRepository
⚠️ SINGLE-INSTANCE ONLY. For dev/test or single-replica deployments.
Production multi-replica deployments MUST use ``RedisRepository`` (or another
networked adapter implementing the ``src.ports.repository`` protocols); these
in-process deques do NOT replicate across replicas and will lose state on
restart / horizontal scale-out.

All three implementations are async (matching the repository ``Protocol``
contracts) and serialize concurrent access with ``asyncio.Lock``; the vitals
store additionally uses ``collections.deque(maxlen=1000)`` to evict the oldest
observations automatically and bound memory growth.
"""

from __future__ import annotations

import asyncio
from collections import deque

from src.core.domain.episode import Episode, EpisodeState
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
        self._lock = asyncio.Lock()
        self._store: dict[str, deque[VitalSignsWindow]] = {}

    async def append(self, patient_id: str, window: VitalSignsWindow) -> None:
        async with self._lock:
            if patient_id not in self._store:
                self._store[patient_id] = deque(maxlen=self._maxlen)
            self._store[patient_id].append(window)

    async def get_window(self, patient_id: str) -> VitalSignsWindow | None:
        async with self._lock:
            windows = self._store.get(patient_id)
            if not windows:
                return None
            return windows[-1]

    async def get_history(self, patient_id: str) -> list[VitalSignsWindow]:
        async with self._lock:
            windows = self._store.get(patient_id)
            if windows is None:
                return []
            return list(windows)

    async def clear_old(self, patient_id: str) -> int:
        async with self._lock:
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
        self._lock = asyncio.Lock()
        self._episodes: dict[str, Episode] = {}
        self._active_by_patient: dict[str, str] = {}
        self._windows: dict[str, VitalSignsWindow] = {}

    async def create(self, patient_id: str) -> Episode:
        async with self._lock:
            episode = Episode(episode_id=f"E-{patient_id}", patient_id=patient_id)
            self._episodes[episode.episode_id] = episode
            self._active_by_patient[patient_id] = episode.episode_id
            return episode

    async def get(self, episode_id: str) -> Episode | None:
        async with self._lock:
            return self._episodes.get(episode_id)

    async def get_active_by_patient(self, patient_id: str) -> Episode | None:
        async with self._lock:
            episode_id = self._active_by_patient.get(patient_id)
            if episode_id is None:
                return None
            return self._episodes.get(episode_id)

    async def get_all_active_by_patient(self, patient_id: str) -> list[Episode]:
        """Return all currently-active episodes for a patient (usually 1)."""
        async with self._lock:
            episode_id = self._active_by_patient.get(patient_id)
            if episode_id is None:
                return []
            episode = self._episodes.get(episode_id)
            return [episode] if episode is not None else []

    async def transition(
        self,
        episode_id: str,
        trigger: str,
        assessment: DeteriorationAssessment,
    ) -> Episode:
        async with self._lock:
            episode = self._episodes.get(episode_id)
            if episode is None:
                raise KeyError(f"Unknown episode: {episode_id}")

            state = EpisodeState(assessment.severity)
            if state.value not in {e.value for e in EpisodeState}:
                state = EpisodeState.NORMAL
            episode.state = state
            episode.available_vitals = set(assessment.contributing_factors)
            episode.updated_at = episode.updated_at.now()
            self._episodes[episode_id] = episode

            # An EMERGENCY/critical transition marks the episode no longer
            # "active" for new auto-creation lookups of the same patient.
            if state in (EpisodeState.EMERGENCY,):
                self._active_by_patient.pop(episode.patient_id, None)

            return episode

    async def update_window(self, episode_id: str, window: VitalSignsWindow) -> Episode:
        async with self._lock:
            episode = self._episodes.get(episode_id)
            if episode is None:
                # Window-only updates for a just-created patient may arrive
                # before an explicit episode; record lazily.
                raise KeyError(f"Unknown episode: {episode_id}")
            self._windows[episode_id] = window
            episode.updated_at = episode.updated_at.now()
            return episode


class InMemoryAssessmentRepository(AssessmentRepository):
    """Append-only audit log bounded by ``MAX_AUDIT_ENTRIES``."""

    def __init__(self, maxlen: int = MAX_AUDIT_ENTRIES) -> None:
        self._maxlen = maxlen
        self._lock = asyncio.Lock()
        self._audit: dict[str, deque[DeteriorationAssessment]] = {}

    async def append_assessment(
        self,
        episode_id: str,
        assessment: DeteriorationAssessment,
    ) -> None:
        async with self._lock:
            if episode_id not in self._audit:
                self._audit[episode_id] = deque(maxlen=self._maxlen)
            self._audit[episode_id].append(assessment)

    async def get_audit_trail(self, episode_id: str) -> list[DeteriorationAssessment]:
        async with self._lock:
            return list(self._audit.get(episode_id, []))


__all__ = [
    "InMemoryVitalsRepository",
    "InMemoryEpisodeRepository",
    "InMemoryAssessmentRepository",
    "MAX_AUDIT_ENTRIES",
    "MAX_WINDOWS_PER_PATIENT",
]
