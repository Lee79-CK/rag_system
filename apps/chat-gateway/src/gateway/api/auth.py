"""인증 API (docs/TDD.md §7.1.5) — aiops_chatbot 로그인 계약 호환.

- 로그인: 브라우저가 계산한 prehash 만 수신 (원문 비밀번호 미전송)
- access token: HS256 JWT (메모리 보관, Authorization: Bearer)
- refresh token: HttpOnly·SameSite=Strict 쿠키 `rag_rt` (path=/api/v1/auth), 매 회 rotation
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Request, Response
from rag_common.passwords import hash_prehash, verify_prehash
from rag_observability import get_logger
from rag_schemas.webchat import AuthUser, LoginRequest, LoginResponse, PasswordChangeRequest

from gateway.api.responses import ApiError
from gateway.core.config import REFRESH_COOKIE, REFRESH_COOKIE_PATH, Settings
from gateway.core.security import hash_refresh_token, issue_access_token, new_refresh_token
from gateway.deps import AppSettings, CurrentUser, Redis, Store
from gateway.metrics import gateway_login_total
from gateway.repos import ChatStore, UserRecord
from gateway.services.rate_limit import allow

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
log = get_logger(__name__)

_INVALID = "이메일 또는 비밀번호가 올바르지 않습니다."


def _require_auth_secrets(settings: Settings) -> None:
    """JWT 키 또는 pepper 가 비면 fail-closed — 빈 키로 서명/해시하지 않는다 (CLAUDE.md Hard rule)."""
    if not settings.jwt_secret() or not settings.password_pepper():
        log.error("auth.secret_missing")
        raise ApiError(
            503, "AUTH_NOT_CONFIGURED", "인증 설정이 완료되지 않았습니다. 관리자에게 문의하세요."
        )


def _auth_user(u: UserRecord) -> AuthUser:
    return AuthUser(
        id=u.id,
        email=u.email,
        display_name=u.display_name,
        role="admin" if u.role == "admin" else "user",
        avatar_url=u.avatar_url,
        must_change_password=u.must_change_password,
    )


def _issue_session(
    settings: Settings, store: ChatStore, response: Response, user: UserRecord
) -> LoginResponse:
    _require_auth_secrets(settings)
    raw, digest = new_refresh_token()
    ttl = timedelta(days=settings.refresh_ttl_days)
    store.create_refresh(user.id, digest, datetime.now(UTC) + ttl)
    response.set_cookie(
        REFRESH_COOKIE,
        raw,
        max_age=int(ttl.total_seconds()),
        path=REFRESH_COOKIE_PATH,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
    )
    return LoginResponse(
        access_token=issue_access_token(settings, user_id=user.id, role=user.role),
        expires_in=settings.chat_access_ttl_seconds,
        user=_auth_user(user),
    )


@router.post("/login", response_model=LoginResponse)
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    settings: AppSettings,
    store: Store,
    redis: Redis,
) -> LoginResponse:
    email = body.email.strip().lower()
    ip = request.client.host if request.client else "unknown"
    limit = settings.rate_limit_login_per_min
    if not (
        await allow(redis, f"auth:rl:email:{email}", limit)
        and await allow(redis, f"auth:rl:ip:{ip}", limit * 5)
    ):
        gateway_login_total.labels("rate_limited").inc()
        raise ApiError(
            429, "RATE_LIMITED", "로그인 시도가 너무 많습니다. 잠시 후 다시 시도해 주세요."
        )
    _require_auth_secrets(settings)

    # replay 방지: timestamp 허용 오차 + client_nonce 1회성
    skew = abs(int(time.time() * 1000) - body.timestamp) / 1000
    nonce_fresh = await redis.set(f"auth:nonce:{body.client_nonce}", "1", nx=True, ex=600)
    if skew > settings.login_max_clock_skew_seconds or not nonce_fresh:
        gateway_login_total.labels("replay").inc()
        raise ApiError(400, "INVALID_REQUEST", "요청이 만료되었습니다. 다시 시도해 주세요.")

    user = store.get_user_by_email(email)
    usable = user is not None and user.is_active and not user.is_bot
    stored = user.password_hash if usable and user is not None else None
    ok = verify_prehash(stored, body.prehash, settings.password_pepper())  # 항상 동일 비용
    if not (usable and ok) or user is None:
        gateway_login_total.labels("invalid").inc()
        raise ApiError(401, "INVALID_CREDENTIALS", _INVALID)

    gateway_login_total.labels("ok").inc()
    log.info("login_ok", user_id=user.id)
    return _issue_session(settings, store, response, user)


@router.post("/refresh", response_model=LoginResponse)
async def refresh(
    request: Request, response: Response, settings: AppSettings, store: Store
) -> LoginResponse:
    raw = request.cookies.get(REFRESH_COOKIE, "")
    user_id = store.consume_refresh(hash_refresh_token(raw)) if raw else None
    user = store.get_user(user_id) if user_id else None
    if user is None or not user.is_active:
        response.delete_cookie(REFRESH_COOKIE, path=REFRESH_COOKIE_PATH)
        raise ApiError(401, "SESSION_EXPIRED", "세션이 만료되었습니다. 다시 로그인해 주세요.")
    return _issue_session(settings, store, response, user)


@router.post("/logout", status_code=204)
async def logout(request: Request, store: Store) -> Response:
    raw = request.cookies.get(REFRESH_COOKIE, "")
    if raw:
        store.revoke_refresh(hash_refresh_token(raw))
    resp = Response(status_code=204)
    resp.delete_cookie(REFRESH_COOKIE, path=REFRESH_COOKIE_PATH)
    return resp


@router.get("/me", response_model=AuthUser)
async def me(user: CurrentUser) -> AuthUser:
    return _auth_user(user)


@router.post("/password/change", status_code=204)
async def change_password(
    body: PasswordChangeRequest, user: CurrentUser, settings: AppSettings, store: Store
) -> Response:
    _require_auth_secrets(settings)
    pepper = settings.password_pepper()
    if not verify_prehash(user.password_hash, body.current_prehash, pepper):
        raise ApiError(400, "INVALID_CREDENTIALS", "현재 비밀번호가 올바르지 않습니다.")
    if body.current_prehash == body.new_prehash:
        raise ApiError(400, "PASSWORD_REUSED", "현재 비밀번호와 다른 비밀번호를 사용해 주세요.")
    policy = body.policy or {}
    # 원문은 서버에 오지 않으므로 클라이언트가 보낸 정책 메타(길이/문자종류)로 2차 확인
    # (chat-web validatePasswordPolicy: 최소 12자, 3종 이상 — aiops AUTH-02 와 동일)
    if policy.get("length", 0) < 12 or policy.get("kinds", 0) < 3:
        raise ApiError(
            400, "PASSWORD_POLICY", "비밀번호는 12자 이상, 3종류 이상 문자를 포함해야 합니다."
        )
    store.set_password(user.id, hash_prehash(body.new_prehash, pepper))
    return Response(status_code=204)
