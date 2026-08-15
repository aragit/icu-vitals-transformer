"""Dependency-injection container (application singletons + port wiring).

Holds the singleton repositories and the ``ClinicalAssessmentService`` wired with
a ``SafetyShell`` around the deterministic forecast backend. New adapters (REST
routes, MCP tools) pull shared state from here rather than touching
module-level globals.

Backend selection: ``REPOSITORY_BACKEND=redis`` activates the multi-replica
Redis adapters (from ``src.adapters.storage.contrib``, an optional
``[redis]`` extra) when a Redis client is reachable; otherwise the in-process
``InMemory*`` dev adapters are used. Redis is therefore never a hard runtime
dependency of the default dev/test path.
"""

from __future__ import annotations

import os

from src.adapters.forecast.deterministic import DeterministicForecastBackend
from src.adapters.storage.memory import (
    InMemoryAssessmentRepository,
    InMemoryEpisodeRepository,
    InMemoryVitalsRepository,
)
from src.core.safety.shell import SafetyShell
from src.core.services.clinical_assessment import ClinicalAssessmentService
from src.observability.metrics import SAFETY_SHELL_FALLBACK_TOTAL, STALE_DATA_WARNING_TOTAL
from src.ports.forecaster import ForecastBackend
from src.ports.repository import (
    AssessmentRepository,
    EpisodeRepository,
    VitalsRepository,
)

_vitals_repo: VitalsRepository | None = None
_episode_repo: EpisodeRepository | None = None
_assessment_repo: AssessmentRepository | None = None
_clinical_service: ClinicalAssessmentService | None = None

_REDIS_REQUESTED = os.environ.get("REPOSITORY_BACKEND", "memory").lower() == "redis"


def _use_redis() -> bool:
    """True when Redis backend is requested AND reachable (dev-safe fallback).

    The Redis adapter lives under ``src.adapters.storage.contrib`` and is an
    optional dependency (``pip install icu-vitals-transformer[redis]``); a
    missing package is treated as "not available" rather than an error.
    """
    if not _REDIS_REQUESTED:
        return False
    try:
        from src.adapters.storage.contrib.redis import is_redis_available
    except ImportError:
        return False
    return is_redis_available()


def get_vitals_repo() -> VitalsRepository:
    global _vitals_repo
    if _vitals_repo is None:
        if _use_redis():
            from src.adapters.storage.contrib.redis import RedisVitalsRepository

            _vitals_repo = RedisVitalsRepository()
        else:
            _vitals_repo = InMemoryVitalsRepository()
    return _vitals_repo


def get_episode_repo() -> EpisodeRepository:
    global _episode_repo
    if _episode_repo is None:
        if _use_redis():
            from src.adapters.storage.contrib.redis import RedisEpisodeRepository

            _episode_repo = RedisEpisodeRepository()
        else:
            _episode_repo = InMemoryEpisodeRepository()
    return _episode_repo


def get_assessment_repo() -> AssessmentRepository:
    global _assessment_repo
    if _assessment_repo is None:
        if _use_redis():
            from src.adapters.storage.contrib.redis import RedisAssessmentRepository

            _assessment_repo = RedisAssessmentRepository()
        else:
            _assessment_repo = InMemoryAssessmentRepository()
    return _assessment_repo


def get_forecast_backend() -> ForecastBackend:
    return DeterministicForecastBackend()


def get_clinical_service() -> ClinicalAssessmentService:
    global _clinical_service
    if _clinical_service is None:
        backend: ForecastBackend = SafetyShell(
            get_forecast_backend(),
            on_fallback=SAFETY_SHELL_FALLBACK_TOTAL.inc,
            on_stale_data=STALE_DATA_WARNING_TOTAL.inc,
        )
        _clinical_service = ClinicalAssessmentService(
            vitals_repo=get_vitals_repo(),
            episode_repo=get_episode_repo(),
            backend=backend,
            assessment_repo=get_assessment_repo(),
        )
    return _clinical_service


def reset_dependencies() -> None:
    """Clear singleton caches (primarily for tests)."""
    global _vitals_repo, _episode_repo, _assessment_repo, _clinical_service
    _vitals_repo = None
    _episode_repo = None
    _assessment_repo = None
    _clinical_service = None


__all__ = [
    "get_vitals_repo",
    "get_episode_repo",
    "get_assessment_repo",
    "get_forecast_backend",
    "get_clinical_service",
    "reset_dependencies",
]
