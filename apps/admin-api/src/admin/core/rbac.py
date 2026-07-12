"""역할 기반 접근 제어 (RBAC) — docs/TDD.md §7.5, §22.5.

인증(DEC-003 PoC 확정): 자체 세션 없이 Reverse Proxy 헤더 신뢰 방식.
Ingress 뒤에서 `X-Auth-User` 헤더를 읽고 `admin_users`와 매칭.
`AuthBackend` 인터페이스로 Keycloak/LDAP 교체 가능.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, override

from fastapi import Depends, Header, HTTPException, status
from rag_common import new_request_id
from rag_schemas import ErrorDetail, ErrorResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from admin.db.models import AdminUser
from admin.db.session import get_db

# 역할 4종 (§7.5).
SYS_ADMIN = "SYS_ADMIN"
DOC_ADMIN = "DOC_ADMIN"
QUALITY_EVALUATOR = "QUALITY_EVALUATOR"
AUDITOR = "AUDITOR"
ALL_ROLES = frozenset({SYS_ADMIN, DOC_ADMIN, QUALITY_EVALUATOR, AUDITOR})


@dataclass(slots=True)
class Principal:
    """인증된 Admin 사용자."""

    id: str
    login_id: str
    display_name: str
    roles: frozenset[str]


class AuthBackend(Protocol):
    """인증 백엔드 인터페이스. HeaderAuth(PoC) → Keycloak/LDAP 교체 지점."""

    def authenticate(self, db: Session, *, auth_user: str | None) -> Principal | None: ...


class HeaderAuthBackend:
    """`X-Auth-User` 헤더 → admin_users lookup (DEC-003)."""

    @override
    def authenticate(self, db: Session, *, auth_user: str | None) -> Principal | None:
        if not auth_user:
            return None
        user = db.execute(
            select(AdminUser).where(AdminUser.login_id == auth_user)
        ).scalar_one_or_none()
        if user is None or user.status != "ACTIVE":
            return None
        return Principal(
            id=str(user.id),
            login_id=user.login_id,
            display_name=user.display_name,
            roles=frozenset(r.name for r in user.roles),
        )


# 기본 백엔드(교체 가능). 테스트는 dependency_overrides로 대체한다.
_backend: AuthBackend = HeaderAuthBackend()


def _error(code: str, message: str, http_status: int) -> HTTPException:
    body = ErrorResponse(error=ErrorDetail(code=code, message=message, request_id=new_request_id()))
    return HTTPException(status_code=http_status, detail=body.model_dump())


def get_current_principal(
    x_auth_user: str | None = Header(default=None, alias="X-Auth-User"),
    db: Session = Depends(get_db),
) -> Principal:
    """현재 요청의 인증 주체. 미인증 → 401."""
    principal = _backend.authenticate(db, auth_user=x_auth_user)
    if principal is None:
        raise _error("UNAUTHENTICATED", "인증되지 않은 요청입니다.", status.HTTP_401_UNAUTHORIZED)
    return principal


def require_roles(*roles: str):
    """지정된 역할 중 하나 이상을 가진 주체만 통과시키는 FastAPI 의존성 팩토리.

    사용: `dependencies=[Depends(require_roles(SYS_ADMIN, DOC_ADMIN))]`
    또는 핸들러 인자: `principal: Principal = Depends(require_roles("SYS_ADMIN"))`
    """
    required = frozenset(roles)

    def _dep(principal: Principal = Depends(get_current_principal)) -> Principal:
        if required and principal.roles.isdisjoint(required):
            raise _error(
                "FORBIDDEN",
                f"권한이 없습니다. 필요한 역할: {sorted(required)}",
                status.HTTP_403_FORBIDDEN,
            )
        return principal

    return _dep
