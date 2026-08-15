"""Port protocols for persistence adapters (hexagonal 'driven' adapters).

These ``typing.Protocol`` definitions are framework-agnostic (Core Isolation
invariant applies). Adapters in ``src/adapters/storage`` and
``src/adapters/episode`` implement them.

The repository contract is intentionally async so that an in-process
``asyncio.Lock`` can serialize concurrent coroutine access while the methods
remain callable from both ``async`` service code and (via ``anyio``) from
short-lived sync wrappers at the adapter boundary.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from src.core.domain.episode import Episode
from src.core.domain.forecast import DeteriorationAssessment
from src.core.domain.vitals import VitalSignsWindow


@runtime_checkable
class VitalsRepository(Protocol):
    """Read/write access to a patient's recent vital-sign windows."""

    async def append(self, patient_id: str, window: VitalSignsWindow) -> None:
        ...

    async def get_window(self, patient_id: str) -> VitalSignsWindow | None:
        ...

    async def get_history(self, patient_id: str) -> list[VitalSignsWindow]:
        ...

    async def clear_old(self, patient_id: str) -> int:
        """Drop stale observations for a patient; returns the count removed."""
        ...


@runtime_checkable
class EpisodeRepository(Protocol):
    """Lifecycle management for clinical episodes."""

    async def create(self, patient_id: str) -> Episode:
        ...

    async def get(self, episode_id: str) -> Episode | None:
        ...

    async def get_active_by_patient(self, patient_id: str) -> Episode | None:
        ...

    async def get_all_active_by_patient(self, patient_id: str) -> list[Episode]:
        """All active episodes for a patient (supports multi-episode lookup)."""
        ...

    async def transition(
        self,
        episode_id: str,
        trigger: str,
        assessment: DeteriorationAssessment,
    ) -> Episode:
        ...

    async def update_window(self, episode_id: str, window: VitalSignsWindow) -> Episode:
        ...


@runtime_checkable
class AssessmentRepository(Protocol):
    """Audit-trail persistence for deterioration assessments."""

    async def append_assessment(
        self,
        episode_id: str,
        assessment: DeteriorationAssessment,
    ) -> None:
        ...

    async def get_audit_trail(self, episode_id: str) -> list[DeteriorationAssessment]:
        ...
