"""Unit tests for the Redis storage adapters (``src/adapters/storage/contrib/redis.py``).

The Redis data clients are injected as ``unittest.mock.AsyncMock`` objects so
the suite never requires a live Redis server. This exercises every branch of
the adapter against a deterministic in-process fake, keeping CI hermetic while
still validating the Sorted-Set / Hash / List / index-set wiring.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.adapters.storage.contrib.redis import (
    RedisAssessmentRepository,
    RedisEpisodeRepository,
    RedisVitalsRepository,
    is_redis_available,
)
from src.core.domain.episode import Episode
from src.core.domain.forecast import DeteriorationAssessment
from src.core.domain.vitals import VitalSignsWindow

pytestmark = pytest.mark.unit


def _window(hr: float | None = 72.0) -> VitalSignsWindow:
    return VitalSignsWindow(
        patient_id="PT-001",
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


def _mock_redis(**overrides: Any) -> AsyncMock:
    """An async-flavoured Redis mock with a transactional pipeline.

    All direct client methods (``zrevrange``, ``sadd``, ``rpush`` …) are
    auto-created ``AsyncMock``s so ``await self._redis.<method>(...)`` resolves;
    ``pipeline`` is a *sync* ``MagicMock`` returning a pipeline whose queued
    commands are sync calls and whose ``execute`` is awaited.
    """
    redis = AsyncMock()
    pipeline = MagicMock(
        zadd=MagicMock(),
        expire=MagicMock(),
        hset=MagicMock(),
        hincrby=MagicMock(),
        sadd=MagicMock(),
        srem=MagicMock(),
        execute=AsyncMock(return_value=[None, None]),
    )
    redis.pipeline = MagicMock(return_value=pipeline)
    for name, value in overrides.items():
        setattr(redis, name, value)
    return redis


def _hash_from_episode(episode_id: str, patient_id: str) -> dict[str, Any]:
    ep = Episode(episode_id=episode_id, patient_id=patient_id)
    return {
        "episode_id": ep.episode_id,
        "patient_id": ep.patient_id,
        "available_vitals": "[]",
        "created_at": ep.created_at.isoformat(),
        "updated_at": ep.updated_at.isoformat(),
    }


class TestRedisVitalsRepository:
    async def test_append_then_get_window(self) -> None:
        redis = _mock_redis(zrevrange=AsyncMock(return_value=[_window().model_dump_json()]))
        repo = RedisVitalsRepository(client=redis)
        await repo.append("PT-001", _window())
        assert redis.pipeline.called
        window = await repo.get_window("PT-001")
        assert window is not None and window.heart_rate == 72.0

    async def test_get_window_returns_none_when_empty(self) -> None:
        redis = _mock_redis(zrevrange=AsyncMock(return_value=[]))
        repo = RedisVitalsRepository(client=redis)
        assert await repo.get_window("NOPE") is None

    async def test_get_history(self) -> None:
        w = _window().model_dump_json()
        redis = _mock_redis(zrange=AsyncMock(return_value=[w, w]))
        repo = RedisVitalsRepository(client=redis)
        history = await repo.get_history("PT-001")
        assert len(history) == 2
        assert all(h.heart_rate == 72.0 for h in history)

    async def test_clear_old_returns_int(self) -> None:
        redis = _mock_redis(zremrangebyscore=AsyncMock(return_value=3))
        repo = RedisVitalsRepository(client=redis)
        removed = await repo.clear_old("PT-001")
        assert removed == 3
        args = redis.zremrangebyscore.call_args.args
        assert args[0] == "vitals:PT-001"


class TestRedisEpisodeRepository:
    async def test_create_and_active_lookup(self) -> None:
        redis = _mock_redis(
            hgetall=AsyncMock(return_value={}),
            smembers=AsyncMock(return_value=set()),
        )
        repo = RedisEpisodeRepository(client=redis)
        ep = await repo.create("PT-001")
        assert ep.episode_id.startswith("E-")
        assert len(ep.episode_id) > len("PT-001") + 2  # UUID suffix present
        assert ep.patient_id == "PT-001"
        # Point the mocks at the generated episode id so read-back matches.
        created_hash = _hash_from_episode(ep.episode_id, "PT-001")
        redis.hgetall = AsyncMock(return_value=created_hash)
        redis.smembers = AsyncMock(return_value={ep.episode_id})
        fetched = await repo.get(ep.episode_id)
        assert fetched is not None and fetched.episode_id == ep.episode_id
        active = await repo.get_active_by_patient("PT-001")
        assert active is not None and active.episode_id == ep.episode_id

    async def test_get_returns_none_when_unknown(self) -> None:
        redis = _mock_redis(hgetall=AsyncMock(return_value={}))
        repo = RedisEpisodeRepository(client=redis)
        assert await repo.get("MISSING") is None

    async def test_get_active_returns_none_when_no_members(self) -> None:
        redis = _mock_redis(smembers=AsyncMock(return_value=set()))
        repo = RedisEpisodeRepository(client=redis)
        assert await repo.get_active_by_patient("PT-001") is None

    async def test_get_all_active_multi(self) -> None:
        redis = _mock_redis(
            smembers=AsyncMock(return_value={"E-1", "E-2"}),
            hgetall=AsyncMock(return_value=_hash_from_episode("E-1", "PT-001")),
        )
        repo = RedisEpisodeRepository(client=redis)
        all_active = await repo.get_all_active_by_patient("PT-001")
        assert len(all_active) == 2

    async def test_update_window_unknown_raises_keyerror(self) -> None:
        redis = _mock_redis(hgetall=AsyncMock(return_value={}))
        repo = RedisEpisodeRepository(client=redis)
        with pytest.raises(KeyError):
            await repo.update_window("MISSING", _window())

    async def test_update_window_existing_syncs_available_vitals(self) -> None:
        redis = _mock_redis(
            hgetall=AsyncMock(return_value=_hash_from_episode("E-PT-001", "PT-001"))
        )
        repo = RedisEpisodeRepository(client=redis)
        ep = await repo.update_window("E-PT-001", _window(hr=90.0))
        assert ep.episode_id == "E-PT-001"
        assert "heart_rate" in ep.available_vitals
        assert "avpu" in ep.available_vitals

    async def test_from_hash_defaults_when_missing(self) -> None:
        redis = RedisEpisodeRepository(client=_mock_redis())
        ep = redis._from_hash(
            {"episode_id": "E-X", "patient_id": "PT-001"}
        )
        assert ep.episode_id == "E-X"
        assert ep.patient_id == "PT-001"
        assert ep.available_vitals == set()


class TestRedisAssessmentRepository:
    async def test_append_and_retrieve_audit_trail(self) -> None:
        entries = [
            DeteriorationAssessment(
                patient_id="PT-001", dds_score=float(i), severity="NORMAL"
            ).model_dump_json()
            for i in range(2)
        ]
        redis = _mock_redis(lrange=AsyncMock(return_value=entries))
        repo = RedisAssessmentRepository(client=redis)
        for i in range(2):
            await repo.append_assessment(
                "E-1",
                DeteriorationAssessment(
                    patient_id="PT-001", dds_score=float(i), severity="NORMAL"
                ),
            )
        redis.ltrim.assert_awaited()
        trail = await repo.get_audit_trail("E-1")
        assert len(trail) == 2
        assert trail[0].dds_score == 0.0

    async def test_get_audit_trail_empty(self) -> None:
        redis = _mock_redis(lrange=AsyncMock(return_value=[]))
        repo = RedisAssessmentRepository(client=redis)
        assert await repo.get_audit_trail("NOPE") == []


class TestIsRedisAvailable:
    async def test_sync_ping_true(self) -> None:
        client = MagicMock()
        client.ping.return_value = True
        assert is_redis_available(client) is True

    async def test_sync_ping_pong_string(self) -> None:
        client = MagicMock()
        client.ping.return_value = "PONG"
        assert is_redis_available(client) is True

    async def test_sync_ping_falsey(self) -> None:
        client = MagicMock()
        client.ping.return_value = 0
        assert is_redis_available(client) is False

    async def test_sync_ping_raises(self) -> None:
        client = MagicMock()
        client.ping.side_effect = ConnectionRefusedError("nope")
        assert is_redis_available(client) is False

    async def test_async_coroutine_ping_is_not_callable_result(self) -> None:
        client = MagicMock()

        async def _async_ping() -> bool:
            return True

        coro = _async_ping()
        client.ping.return_value = coro
        try:
            # A coroutine is neither bool nor str -> False branch.
            assert is_redis_available(client) is False
        finally:
            coro.close()
