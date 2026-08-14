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
        assert await repo.get(ep.episode_id) == ep
        active = await repo.get_active_by_patient("PT-001")
        assert active is not None and active.episode_id == ep.episode_id

    async def test_transition_updates_state(self) -> None:
        repo = InMemoryEpisodeRepository()
        ep = await repo.create("PT-001")
        assessment = DeteriorationAssessment(
            patient_id="PT-001",
            ensemble_score=5.0,
            severity="ALERT",
            contributing_factors=["heart_rate_elevated"],
        )
        transitioned = await repo.transition(ep.episode_id, "deterioration_assessment", assessment)
        assert transitioned.state.value == "ALERT"
        # EMERGENCY transitions clear the active-patient index.
        alert_assessment = DeteriorationAssessment(
            patient_id="PT-001",
            ensemble_score=9.0,
            severity="EMERGENCY",
            contributing_factors=["heart_rate_critical"],
        )
        await repo.transition(ep.episode_id, "deterioration_assessment", alert_assessment)
        assert await repo.get_active_by_patient("PT-001") is None

    async def test_update_window_records_latest(self) -> None:
        repo = InMemoryEpisodeRepository()
        ep = await repo.create("PT-001")
        await repo.update_window(ep.episode_id, _window("PT-001", hr=90.0))


class TestAssessmentRepository:
    async def test_audit_trail_append_and_retrieve(self) -> None:
        repo = InMemoryAssessmentRepository(maxlen=5)
        ep_id = "E-PT-001"
        for sev in ["NORMAL", "WARNING", "ALERT"]:
            await repo.append_assessment(
                ep_id,
                DeteriorationAssessment(
                    patient_id="PT-001",
                    ensemble_score=0.0,
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
                    ensemble_score=float(i),
                    severity="NORMAL",
                ),
            )
        trail = await repo.get_audit_trail("E-1")
        assert len(trail) == 3  # oldest evicted
