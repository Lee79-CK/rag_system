"""FastAPI 의존성 주입 (§7.1 — 테스트에서 dependency_overrides로 교체 가능).

redis(async, dedup/rate-limit/health), repos(SQLAlchemy), enqueuer(RQ, sync redis)를
프로세스 싱글턴으로 제공한다.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from rag_common import TTLCache
from rag_schemas import ChannelBinding

from bridge.core.config import Settings, get_settings
from bridge.repos import (
    BindingRepo,
    EventRepo,
    FeedbackRepo,
    SqlBindingRepo,
    SqlEventRepo,
    SqlFeedbackRepo,
    _make_engine,
)
from bridge.services.job_enqueuer import Enqueuer, RqEnqueuer

# --- 프로세스 로컬 싱글턴 캐시 ---
_async_redis: Any | None = None
_sync_redis: Any | None = None
_engine: Any | None = None
_binding_cache: TTLCache[str, ChannelBinding] | None = None


def get_async_redis(settings: Settings) -> Any:
    """dedup/rate-limit/health용 async Redis 클라이언트 (싱글턴)."""
    global _async_redis
    if _async_redis is None:
        import redis.asyncio as aioredis

        _async_redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _async_redis


def get_sync_redis(settings: Settings) -> Any:
    """RQ enqueue용 동기 Redis 연결 (싱글턴)."""
    global _sync_redis
    if _sync_redis is None:
        import redis

        _sync_redis = redis.Redis.from_url(settings.redis_url)
    return _sync_redis


def _get_engine(settings: Settings) -> Any:
    global _engine
    if _engine is None:
        _engine = _make_engine(settings.postgres_dsn())
    return _engine


# --------------------------------------------------------------------------- #
# FastAPI dependency 함수 (app.dependency_overrides 키로 사용)
# --------------------------------------------------------------------------- #


def provide_settings() -> Settings:
    return get_settings()


def provide_redis() -> Any:
    return get_async_redis(get_settings())


@lru_cache
def get_binding_cache_singleton() -> TTLCache[str, ChannelBinding]:
    return TTLCache(get_settings().bridge_binding_cache_ttl_seconds)


def provide_binding_cache() -> TTLCache[str, ChannelBinding]:
    return get_binding_cache_singleton()


def provide_binding_repo() -> BindingRepo:
    return SqlBindingRepo(_get_engine(get_settings()))


def provide_event_repo() -> EventRepo:
    return SqlEventRepo(_get_engine(get_settings()))


def provide_feedback_repo() -> FeedbackRepo:
    return SqlFeedbackRepo(_get_engine(get_settings()))


def provide_enqueuer() -> Enqueuer:
    return RqEnqueuer(get_sync_redis(get_settings()))
