"""감사 로그 미들웨어 — docs/TDD.md §7.5, FR-AUTH-005.

모든 mutating(POST/PUT/PATCH/DELETE) 요청을 audit_logs에 기록한다.
actor(X-Auth-User) / action(method path) / target(path) / result(OK|DENIED|ERROR).
Secret 값은 기록하지 않는다 — 경로/상태만.
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from admin.db.models import AuditLog
from admin.db.session import get_sessionmaker

_MUTATING = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def _result(status_code: int) -> str:
    if status_code < 400:
        return "OK"
    if status_code in (401, 403):
        return "DENIED"
    return "ERROR"


class AuditMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):  # noqa: ANN001
        response: Response = await call_next(request)
        if request.method not in _MUTATING:
            return response
        # health/metrics 는 감사 대상 아님.
        path = request.url.path
        if path.startswith("/health") or path == "/metrics":
            return response

        actor = request.headers.get("X-Auth-User") or "anonymous"
        try:
            session_factory = get_sessionmaker()
            with session_factory() as session:
                session.add(
                    AuditLog(
                        actor=actor,
                        action=f"{request.method} {path}",
                        target=path,
                        result=_result(response.status_code),
                        detail={"status_code": response.status_code},
                    )
                )
                session.commit()
        except Exception:  # noqa: BLE001 — 감사 기록 실패가 요청을 깨뜨리면 안 됨.
            pass
        return response
