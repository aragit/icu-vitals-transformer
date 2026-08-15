"""Integration tests for InMemoryEpisodeRepository available_vitals wiring.

Phase 1 hardening (docs/BASELINE.md): ``available_vitals`` must be derived from
the observed ``VitalSignsWindow`` (never from assessment ``contributing_factors``,
which are scoring artifacts like ``"heart_rate_critical"``).
"""

from __future__ import annotations

import pytest

from src.adapters.storage.memory import InMemoryEpisodeRepository
from src.core.domain.vitals import VitalSignsWindow

pytestmark = pytest.mark.integration


def _window(patient_id: str = "PT-001", **overrides: object) -> VitalSignsWindow:
    base: dict[str, object] = {
        "patient_id": patient_id,
        "window_start": "2026-07-02T08:00:00",
        "window_end": "2026-07-02T08:05:00",
    }
    base.update(overrides)
    return VitalSignsWindow(**base)  # type: ignore[arg-type]


def _hr_spo2_window(patient_id: str = "PT-001") -> VitalSignsWindow:
    return _window(
        patient_id=patient_id,
        heart_rate=72.0,
        systolic_bp=None,
        diastolic_bp=None,
        spo2=98.0,
        respiratory_rate=None,
        temperature=None,
        avpu=None,
    )


class TestAvailableVitals:
    async def test_update_window_records_observed_vitals(self) -> None:
        repo = InMemoryEpisodeRepository()
        ep = await repo.create("PT-001")
        await repo.update_window(ep.episode_id, _hr_spo2_window())
        assert ep.available_vitals == {"heart_rate", "spo2"}

    async def test_update_window_includes_avpu_when_present(self) -> None:
        repo = InMemoryEpisodeRepository()
        ep = await repo.create("PT-001")
        await repo.update_window(
            ep.episode_id, _window(patient_id="PT-001", heart_rate=72.0, avpu="P")
        )
        assert ep.available_vitals == {"heart_rate", "avpu"}

    async def test_update_window_does_not_inject_scoring_artifacts(self) -> None:
        repo = InMemoryEpisodeRepository()
        ep = await repo.create("PT-001")
        await repo.update_window(ep.episode_id, _hr_spo2_window())
        # available_vitals reflects the observed window only; a scoring
        # artifact like "respiratory_rate_critical" is never injected.
        assert ep.available_vitals == {"heart_rate", "spo2"}
