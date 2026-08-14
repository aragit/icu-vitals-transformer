"""Unit tests for the DI container (src/dependencies.py)."""

from __future__ import annotations

import pytest

from src.dependencies import (
    get_assessment_repo,
    get_clinical_service,
    get_episode_repo,
    get_forecast_backend,
    get_vitals_repo,
    reset_dependencies,
)
from src.ports.forecaster import ForecastBackend
from src.ports.repository import (
    AssessmentRepository,
    EpisodeRepository,
    VitalsRepository,
)

pytestmark = pytest.mark.unit


class TestDependencyContainer:
    def test_returns_port_types(self) -> None:
        assert isinstance(get_vitals_repo(), VitalsRepository)
        assert isinstance(get_episode_repo(), EpisodeRepository)
        assert isinstance(get_assessment_repo(), AssessmentRepository)
        assert isinstance(get_forecast_backend(), ForecastBackend)

    def test_singleton_identity(self) -> None:
        reset_dependencies()
        a = get_vitals_repo()
        b = get_vitals_repo()
        assert a is b
        reset_dependencies()

    def test_clinical_service_wiring(self) -> None:
        reset_dependencies()
        service = get_clinical_service()
        assert service is get_clinical_service()
        assert isinstance(service._vitals, VitalsRepository)
        assert isinstance(service._episodes, EpisodeRepository)
        assert isinstance(service._assessments, AssessmentRepository)
        from src.core.safety.shell import SafetyShell

        assert isinstance(service._backend, SafetyShell)
        reset_dependencies()
