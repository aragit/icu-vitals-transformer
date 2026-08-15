"""Redis storage adapters (driven storage adapter).

Provides multi-replica-capable implementations of the ``VitalsRepository``
and ``EpisodeRepository`` protocols backed by Redis. Time-series vital windows
are stored in Redis Sorted Sets (``ZADD`` scored by epoch timestamp, 30-day
TTL); episodes are stored as Redis Hashes with an active-patient index set.

Dev/test fallback: ``src/dependencies`` selects this backend only when
``REPOSITORY_BACKEND=redis`` AND a Redis client is reachable; otherwise the
in-process ``InMemory*`` repositories are used, so this module is never a hard
runtime dependency of the default dev/test path.

The Redis client is held as ``Any`` because ``redis-py``'s type stubs expose
sync/async overloads that are impractical to satisfy under strict mypy; this is
an adapter-bound concern and does not leak into the hex core.
"""

from __future__ import annotations

import json as _json
import logging
import uuid
from datetime import datetime
from typing import Any

from src.core.domain.episode import Episode, EpisodeState
from src.core.domain.vitals import VitalSignsWindow
from src.observability.metrics import set_episode_state_gauges
from src.ports.repository import (
    AssessmentRepository,
    EpisodeRepository,
    VitalsRepository,
)

logger = logging.getLogger(__name__)

DEFAULT_TTL_SECONDS: int = 30 * 24 * 3600  # 30 days


class RedisVitalsRepository(VitalsRepository):
    """Time-series vital windows in Redis Sorted Sets (score = epoch seconds)."""

    def __init__(self, client: Any = None, ttl: int = DEFAULT_TTL_SECONDS) -> None:
        self._redis: Any = client if client is not None else _new_client()
        self._ttl = ttl

    def _key(self, patient_id: str) -> str:
        return f"vitals:{patient_id}"

    async def append(self, patient_id: str, window: VitalSignsWindow) -> None:
        score = window.window_end.timestamp()
        member = window.model_dump_json()
        pipe = self._redis.pipeline()
        pipe.zadd(self._key(patient_id), {member: score})
        pipe.expire(self._key(patient_id), self._ttl)
        await pipe.execute()

    async def get_window(self, patient_id: str) -> VitalSignsWindow | None:
        raw = await self._redis.zrevrange(self._key(patient_id), 0, 0, withscores=False)
        if not raw:
            return None
        return VitalSignsWindow.model_validate_json(raw[0])

    async def get_history(self, patient_id: str) -> list[VitalSignsWindow]:
        raw = await self._redis.zrange(self._key(patient_id), 0, -1, withscores=False)
        return [VitalSignsWindow.model_validate_json(entry) for entry in raw]

    async def clear_old(self, patient_id: str) -> int:
        cutoff = datetime.utcnow().timestamp() - self._ttl
        removed: int = await self._redis.zremrangebyscore(
            self._key(patient_id), 0, cutoff
        )
        return int(removed)


class RedisEpisodeRepository(EpisodeRepository):
    """Episode JSON in Redis Hashes with an active-patient index set."""

    def __init__(self, client: Any = None, ttl: int = DEFAULT_TTL_SECONDS) -> None:
        self._redis: Any = client if client is not None else _new_client()
        self._ttl = ttl

    def _ep_key(self, episode_id: str) -> str:
        return f"episode:{episode_id}"

    def _active_key(self, patient_id: str) -> str:
        return f"index:episode:active:{patient_id}"

    def _state_counts_key(self) -> str:
        return "episodes:state_counts"

    async def create(self, patient_id: str) -> Episode:
        episode_id = f"E-{uuid.uuid4().hex[:12]}"
        episode = Episode(episode_id=episode_id, patient_id=patient_id)
        await self._upsert(episode)
        await self._redis.sadd(self._active_key(patient_id), episode.episode_id)
        return episode

    async def get(self, episode_id: str) -> Episode | None:
        raw: Any = await self._redis.hgetall(self._ep_key(episode_id))
        if not raw:
            return None
        return self._from_hash(raw)

    async def get_active_by_patient(self, patient_id: str) -> Episode | None:
        members: Any = await self._redis.smembers(self._active_key(patient_id))
        if not members:
            return None
        episodes: list[Episode] = []
        for member in members:
            ep = await self.get(str(member))
            if ep is not None:
                episodes.append(ep)
        if not episodes:
            return None
        return max(episodes, key=lambda ep: ep.created_at)

    async def get_all_active_by_patient(self, patient_id: str) -> list[Episode]:
        members: Any = await self._redis.smembers(self._active_key(patient_id))
        if not members:
            return []
        out: list[Episode] = []
        for member in members:
            ep = await self.get(str(member))
            if ep is not None:
                out.append(ep)
        return out

    async def transition(self, episode_id: str, trigger: str, assessment: Any) -> Episode:
        severity = getattr(assessment, "severity", "NORMAL")
        state = (
            EpisodeState(severity)
            if severity in EpisodeState._value2member_map_
            else EpisodeState.NORMAL
        )
        raw: Any = await self._redis.hgetall(self._ep_key(episode_id))
        episode = (
            self._from_hash(raw)
            if raw
            else Episode(episode_id=episode_id, patient_id="unknown")
        )
        old_state = episode.state
        episode.state = state
        episode.updated_at = episode.updated_at.now()
        await self._upsert(episode)
        if state in (EpisodeState.EMERGENCY,):
            await self._redis.srem(self._active_key(episode.patient_id), episode.episode_id)

        pipe = self._redis.pipeline()
        pipe.hincrby(self._state_counts_key(), state.value, 1)
        if old_state.value != state.value:
            pipe.hincrby(self._state_counts_key(), old_state.value, -1)
        await pipe.execute()

        raw_counts: dict[str, Any] = await self._redis.hgetall(self._state_counts_key())
        state_counts: dict[str, int] = {}
        for k, v in raw_counts.items():
            key = k.decode() if isinstance(k, bytes) else k
            try:
                state_counts[key] = int(v)
            except (ValueError, TypeError):
                continue
        set_episode_state_gauges(state_counts)

        return episode

    async def update_window(self, episode_id: str, window: VitalSignsWindow) -> Episode:
        raw: Any = await self._redis.hgetall(self._ep_key(episode_id))
        if not raw:
            raise KeyError(f"Unknown episode: {episode_id}")
        episode = self._from_hash(raw)
        available = {
            f for f in (
                "heart_rate", "systolic_bp", "diastolic_bp", "spo2",
                "respiratory_rate", "temperature",
            ) if getattr(window, f) is not None
        }
        if window.avpu is not None:
            available.add("avpu")
        episode.available_vitals = available
        episode.updated_at = episode.updated_at.now()
        await self._upsert(episode)
        return episode

    async def _upsert(self, episode: Episode) -> None:
        hash_data: dict[str, str] = {
            "episode_id": episode.episode_id,
            "patient_id": episode.patient_id,
            "state": episode.state.value,
            "available_vitals": _json.dumps(sorted(episode.available_vitals)),
            "created_at": episode.created_at.isoformat(),
            "updated_at": episode.updated_at.isoformat(),
        }
        pipe = self._redis.pipeline()
        pipe.hset(self._ep_key(episode.episode_id), mapping=hash_data)
        pipe.expire(self._ep_key(episode.episode_id), self._ttl)
        await pipe.execute()

    def _from_hash(self, raw: dict[str, Any]) -> Episode:
        available_vitals = set(_json.loads(raw.get("available_vitals", "[]")))
        now_iso = datetime.utcnow().isoformat()
        return Episode(
            episode_id=raw["episode_id"],
            patient_id=raw["patient_id"],
            state=EpisodeState(raw.get("state", "NORMAL")),
            available_vitals=available_vitals,
            created_at=datetime.fromisoformat(raw.get("created_at", now_iso)),
            updated_at=datetime.fromisoformat(raw.get("updated_at", now_iso)),
        )


class RedisAssessmentRepository(AssessmentRepository):
    """Append-only audit log in a Redis List (bounded via LTRIM after writes)."""

    def __init__(self, client: Any = None, maxlen: int = 10000) -> None:
        self._redis: Any = client if client is not None else _new_client()
        self._maxlen = maxlen

    def _key(self, episode_id: str) -> str:
        return f"audit:{episode_id}"

    async def append_assessment(self, episode_id: str, assessment: Any) -> None:
        await self._redis.rpush(self._key(episode_id), assessment.model_dump_json())
        await self._redis.ltrim(self._key(episode_id), -self._maxlen, -1)

    async def get_audit_trail(self, episode_id: str) -> list[Any]:
        from src.core.domain.forecast import DeteriorationAssessment

        raw: Any = await self._redis.lrange(self._key(episode_id), 0, -1)
        return [DeteriorationAssessment.model_validate_json(entry) for entry in raw]


def _new_client() -> Any:
    from redis.asyncio import Redis

    return Redis()


def is_redis_available(client: Any = None) -> bool:
    """Health-check: True if a Redis server can be reached via PING.

    Uses a synchronous Redis client for the liveness probe so this check stays
    usable from synchronous DI factory code; the (async) data clients used by
    the repositories are constructed separately.
    """
    if client is None:
        try:
            import redis
        except ImportError:
            return False
        try:
            client = redis.Redis()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Redis client unavailable: %s", exc)
            return False
    try:
        ping = client.ping()
        # Async clients return a coroutine; sync clients return a bool/str.
        if isinstance(ping, bool) or isinstance(ping, str):
            return bool(ping)
        return False
    except Exception as exc:  # noqa: BLE001
        logger.warning("Redis ping failed: %s", exc)
        return False


__all__ = [
    "RedisVitalsRepository",
    "RedisEpisodeRepository",
    "RedisAssessmentRepository",
    "is_redis_available",
]
