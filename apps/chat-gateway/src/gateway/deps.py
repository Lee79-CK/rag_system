"""FastAPI 의존성 주입 (§7.1 — 테스트에서 dependency_overrides로 교체 가능).

redis(async, dedup/rate-limit/health), store(SQLAlchemy), enqueuer(RQ, sync redis),
emitter(socket.io server)를 프로세스 싱글턴으로 제공한다.
"""

from __future__ import annotations

from typing import Annotated, Any

from chat_adapter import StreamEmitter
from fastapi import Depends, Request

from gateway.api.responses import ApiError
from gateway.core.config import Settings, get_settings
from gateway.core.security import Principal, verify_access_token
from gateway.repos import ChatStore, SqlChatStore, UserRecord, _make_engine
from gateway.services.job_enqueuer import Enqueuer, RqEnqueuer

# --- 프로세스 로컬 싱글턴 캐시 ---
_async_redis: Any | None = None
_sync_redis: Any | None = None
_store: ChatStore | None = None
_emitter: StreamEmitter | None = None


def get_async_redis(settings: Settings) -> Any:
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


def set_emitter(emitter: StreamEmitter) -> None:
    """main 에서 socket.io AsyncServer 로 구성한 Emitter 를 등록한다."""
    global _emitter
    _emitter = emitter


# --------------------------------------------------------------------------- #
# FastAPI dependency 함수 (app.dependency_overrides 키로 사용)
# --------------------------------------------------------------------------- #


def provide_settings() -> Settings:
    return get_settings()


def provide_redis() -> Any:
    return get_async_redis(get_settings())


def provide_store() -> ChatStore:
    global _store
    if _store is None:
        _store = SqlChatStore(_make_engine(get_settings().postgres_dsn()))
    return _store


def provide_enqueuer() -> Enqueuer:
    return RqEnqueuer(get_sync_redis(get_settings()))


def provide_emitter() -> StreamEmitter:
    if _emitter is None:
        raise RuntimeError("socket.io emitter not configured")
    return _emitter


def _bearer(request: Request) -> str:
    auth = request.headers.get("authorization", "")
    scheme, _, token = auth.partition(" ")
    return token.strip() if scheme.lower() == "bearer" else ""


def provide_principal(
    request: Request, settings: Annotated[Settings, Depends(provide_settings)]
) -> Principal:
    principal = verify_access_token(settings, _bearer(request))
    if principal is None:
        raise ApiError(401, "UNAUTHORIZED", "로그인이 필요합니다.")
    return principal


def provide_current_user(
    principal: Annotated[Principal, Depends(provide_principal)],
    store: Annotated[ChatStore, Depends(provide_store)],
) -> UserRecord:
    user = store.get_user(principal.user_id)
    if user is None or not user.is_active or user.is_bot:
        raise ApiError(401, "UNAUTHORIZED", "로그인이 필요합니다.")
    return user


CurrentUser = Annotated[UserRecord, Depends(provide_current_user)]
Store = Annotated[ChatStore, Depends(provide_store)]
Redis = Annotated[Any, Depends(provide_redis)]
AppSettings = Annotated[Settings, Depends(provide_settings)]
Emitter = Annotated[StreamEmitter, Depends(provide_emitter)]
QueueEnqueuer = Annotated[Enqueuer, Depends(provide_enqueuer)]
