"""엔진 + sessionmaker + get_db() 의존성 (§5.1)."""

from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from admin.core.config import get_settings


@lru_cache
def get_engine() -> Engine:
    settings = get_settings()
    url = settings.sqlalchemy_url
    # SQLite(테스트)와 Postgres(운영) 모두에서 안전한 옵션만 설정.
    connect_args: dict = {}
    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    return create_engine(url, pool_pre_ping=True, connect_args=connect_args)


@lru_cache
def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """FastAPI 의존성. 요청 스코프 세션."""
    session = get_sessionmaker()()
    try:
        yield session
    finally:
        session.close()
