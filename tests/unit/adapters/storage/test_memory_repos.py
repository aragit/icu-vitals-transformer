"""Unit tests for the in-memory bounded repositories."""

from __future__ import annotations

import asyncio

import pytest

from src.adapters.storage.memory import (
    InMemoryAssessmentRepository,
    InMemoryEpisodeRepository,
    InMemoryVitalsRepository,
)
from src.core.domain.forecast import DeteriorationAssessment
from src.core.domain.vitals import VitalSignsWindow

pytestmark = pytest.mark.unit


def _window(pid: str = "PT-001", hr: float | None = 72.0) -> VitalSignsWindow:
    return VitalSignsWindow(
        patient_id=pid,
        window_start="2026-07-02T08:00:00",
        window_end="2026-07-02T08:05:00",
        heart_rate=hr,
        systolic_bp=120.0,
        diastolic_bp=80.0,
        spo2=98.0,
        respiratory_rate=16.0,
        temperature=36.5,
        avpu="A",
    )


class TestVitalsRepository:
    async def test_bounded_deque_evicts_oldest(self) -> None:
        repo = InMemoryVitalsRepository(maxlen=10)
        for i in range(11):
            await repo.append("PT-001", _window("PT-001", hr=70.0 + i))
        history = await repo.get_history("PT-001")
        assert len(history) == 10  # oldest evicted
        assert history[-1].heart_rate == 80.0  # most recent kept
        assert await repo.get_window("PT-001") == history[-1]

    async def test_get_window_empty(self) -> None:
        repo = InMemoryVitalsRepository()
        assert await repo.get_window("NOPE") is None
        assert await repo.get_history("NOPE") == []

    async def test_clear_old_returns_count(self) -> None:
        repo = InMemoryVitalsRepository()
        await repo.append("PT-001", _window("PT-001"))
        await repo.append("PT-001", _window("PT-001"))
        removed = await repo.clear_old("PT-001")
        assert removed == 2
        assert await repo.get_history("PT-001") == []

    async def test_concurrent_appends_are_serialized(self) -> None:
        repo = InMemoryVitalsRepository(maxlen=1000)
        await asyncio.gather(*[repo.append("PT-001", _window("PT-001")) for _ in range(50)])
        assert len(await repo.get_history("PT-001")) == 50


class TestEpisodeRepository:
    async def test_create_and_active_lookup(self) -> None:
        repo = InMemoryEpisodeRepository()
        ep = await repo.create("PT-001")
        assert ep.patient_id == "PT-001"
        assert ep.episode_id.startswith("E-")
        assert await repo.get(ep.episode_id) == ep
        active = await repo.get_active_by_patient("PT-001")
        assert active is not None and active.episode_id == ep.episode_id

    async def test_update_window_records_latest(self) -> None:
        repo = InMemoryEpisodeRepository()
        ep = await repo.create("PT-001")
        updated = await repo.update_window(ep.episode_id, _window("PT-001", hr=90.0))
        assert "heart_rate" in updated.available_vitals
        assert updated.updated_at >= updated.created_at

    async def test_update_persists_mutations(self) -> None:
        repo = InMemoryEpisodeRepository()
        ep = await repo.create("PT-001")
        ep.available_vitals.add("avpu")
        persisted = await repo.update(ep)
        fetched = await repo.get(ep.episode_id)
        assert fetched is not None and "avpu" in fetched.available_vitals
        assert persisted.available_vitals == fetched.available_vitals

    async def test_two_episodes_same_patient_are_unique_and_both_active(self) -> None:
        repo = InMemoryEpisodeRepository()
        ep1 = await repo.create("PT-001")
        ep2 = await repo.create("PT-001")
        assert ep1.episode_id != ep2.episode_id
        assert ep1.episode_id.startswith("E-")
        assert ep2.episode_id.startswith("E-")
        all_active = await repo.get_all_active_by_patient("PT-001")
        assert len(all_active) == 2

    async def test_get_active_returns_most_recent_by_created_at(self) -> None:
        repo = InMemoryEpisodeRepository()
        ep1 = await repo.create("PT-001")
        ep2 = await repo.create("PT-001")
        # Make ep1 strictly newer than ep2 in the stored episode.
        from datetime import timedelta

        repo._episodes[ep1.episode_id].created_at = ep2.created_at + timedelta(seconds=10)
        active = await repo.get_active_by_patient("PT-001")
        assert active is not None and active.episode_id == ep1.episode_id
        ordered = await repo.get_all_active_by_patient("PT-001")
        assert [e.episode_id for e in ordered] == [ep1.episode_id, ep2.episode_id]


class TestAssessmentRepository:
    async def test_audit_trail_append_and_retrieve(self) -> None:
        repo = InMemoryAssessmentRepository(maxlen=5)
        ep_id = "E-PT-001"
        for sev in ["NORMAL", "WARNING", "ALERT"]:
            await repo.append_assessment(
                ep_id,
                DeteriorationAssessment(
                    patient_id="PT-001",
                    dds_score=0.0,
                    severity=sev,
                ),
            )
        trail = await repo.get_audit_trail(ep_id)
        assert [a.severity for a in trail] == ["NORMAL", "WARNING", "ALERT"]
        assert await repo.get_audit_trail("UNKNOWN") == []

    async def test_audit_trail_bounded(self) -> None:
        repo = InMemoryAssessmentRepository(maxlen=3)
        for i in range(5):
            await repo.append_assessment(
                "E-1",
                DeteriorationAssessment(
                    patient_id="PT-001",
                    dds_score=float(i),
                    severity="NORMAL",
                ),
            )
        trail = await repo.get_audit_trail("E-1")
        assert len(trail) == 3  # oldest evicted
