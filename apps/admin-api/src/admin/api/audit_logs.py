"""감사 로그 조회 API — admin-web '시스템 › 감사 로그' (FR-AUTH-005 "누가/언제/무엇을 수행했는지 조회 가능").

GET /api/v1/audit-logs   audit_logs 검색 (행위자·Action/Path·Method·결과·기간), 최신순

기록 주체는 두 가지다.
- AuditMiddleware: 모든 POST/PUT/PATCH/DELETE → action "METHOD /path", target=path, detail={status_code}.
- 핸들러 명시 기록: DOCUMENT_ACL_UPDATE(before/after), ERROR_LOG_VIEW(at/pods) 등 — action 은 대문자 이름.
뷰는 앞의 형식을 method/path 로 풀고, 뒤의 형식은 method 없이 action 그대로 둔다.
조회 자체(GET)는 감사하지 않는다 — 행 내용에 Secret 값이 없기 때문(미들웨어는 경로·상태만 기록).
"""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from admin.api.responses import api_error, envelope
from admin.core.rbac import AUDITOR, SYS_ADMIN, Principal, require_roles
from admin.db.models import AuditLog
from admin.db.session import get_db

router = APIRouter(prefix="/api/v1/audit-logs", tags=["audit-logs"])

METHODS = ("POST", "PUT", "PATCH", "DELETE")
RESULTS = ("OK", "DENIED", "ERROR")


def _aware(ts: dt.datetime | None) -> dt.datetime | None:
    if ts is not None and ts.tzinfo is None:  # SQLite 는 tz 를 잃는다
        return ts.replace(tzinfo=dt.UTC)
    return ts


def _view(row: AuditLog) -> dict:
    method, path = None, None
    head, _, rest = row.action.partition(" ")
    if head in METHODS and rest.startswith("/"):
        method, path = head, rest
    detail = row.detail or {}
    ts = _aware(row.ts)
    return {
        "id": str(row.id),
        "actor": row.actor,
        "method": method,
        "path": path,
        "action": row.action,
        "target": row.target,
        "result": row.result,
        "status_code": detail.get("status_code"),
        "detail": detail or None,
        "created_at": ts.isoformat() if ts else None,
    }


def _contains(column, needle: str):
    return func.lower(column).contains(needle.lower(), autoescape=True)


@router.get("")
def list_audit_logs(
    actor: str | None = Query(default=None, max_length=200),
    action: str | None = Query(
        default=None, max_length=200, description="Action 또는 Path 부분 일치"
    ),
    method: str | None = None,
    result: str | None = None,
    from_: dt.datetime | None = Query(default=None, alias="from"),
    to: dt.datetime | None = None,
    limit: int = Query(default=500, ge=1, le=2000),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles(SYS_ADMIN, AUDITOR)),
) -> dict:
    stmt = select(AuditLog)
    if actor:
        stmt = stmt.where(_contains(AuditLog.actor, actor.strip()))
    if action:
        needle = action.strip()
        stmt = stmt.where(
            or_(_contains(AuditLog.action, needle), _contains(AuditLog.target, needle))
        )
    if method:
        m = method.upper()
        if m not in METHODS:
            raise api_error(
                "INVALID_METHOD",
                "알 수 없는 Method 입니다.",
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                allowed=list(METHODS),
            )
        stmt = stmt.where(AuditLog.action.startswith(f"{m} /", autoescape=True))
    if result:
        r = result.upper()
        if r not in RESULTS:
            raise api_error(
                "INVALID_RESULT",
                "알 수 없는 결과 값입니다.",
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                allowed=list(RESULTS),
            )
        stmt = stmt.where(AuditLog.result == r)
    if from_ is not None:
        stmt = stmt.where(AuditLog.ts >= from_)
    if to is not None:
        stmt = stmt.where(AuditLog.ts <= to)
    if from_ is not None and to is not None and from_ > to:
        raise api_error(
            "INVALID_RANGE",
            "시작 시각이 종료 시각보다 늦습니다.",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    # limit+1 로 잘림 여부를 판단 — 화면이 "최근 N건만 표시" 안내를 띄운다
    rows = db.execute(stmt.order_by(AuditLog.ts.desc()).limit(limit + 1)).scalars().all()
    truncated = len(rows) > limit
    items = [_view(r) for r in rows[:limit]]
    return envelope(items, count=len(items), truncated=truncated, limit=limit)
