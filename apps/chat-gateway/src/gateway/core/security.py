"""토큰 발급/검증 (docs/TDD.md §7.1.5). 토큰 원문은 로그·DB 에 남기지 않는다."""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass

from rag_common import jwt

from gateway.core.config import Settings


@dataclass(frozen=True, slots=True)
class Principal:
    """access token 에서 복원한 요청 주체."""

    user_id: str
    role: str


def issue_access_token(settings: Settings, *, user_id: str, role: str) -> str:
    return jwt.encode(
        {"sub": user_id, "role": role, "typ": "access"},
        settings.jwt_secret(),
        ttl_seconds=settings.chat_access_ttl_seconds,
    )


def verify_access_token(settings: Settings, token: str) -> Principal | None:
    secret = settings.jwt_secret()
    if not token or not secret:
        return None
    try:
        claims = jwt.decode(token, secret)
    except jwt.JWTError:
        return None
    if claims.get("typ") != "access" or not claims.get("sub"):
        return None
    return Principal(user_id=str(claims["sub"]), role=str(claims.get("role", "user")))


def new_refresh_token() -> tuple[str, str]:
    """(쿠키로 내려줄 원문, DB 저장용 sha256) — DB 유출 시에도 세션 탈취 불가."""
    raw = secrets.token_urlsafe(32)
    return raw, hash_refresh_token(raw)


def hash_refresh_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()
