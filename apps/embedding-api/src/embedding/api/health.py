"""Health/metrics 엔드포인트 — docs/TDD.md §17.10.

- /health/live    : 프로세스 생존 → 항상 200
- /health/ready   : 엔진 로딩 완료 시 200, 아니면 503
- /health/startup : 엔진 준비 완료 시 200, 아니면 503 (모델 로딩 1회, §7.3)
- /metrics        : prometheus text
"""

from __future__ import annotations

from fastapi import APIRouter, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

router = APIRouter(tags=["health"])


def _engine_ready(request: Request) -> bool:
    return getattr(request.app.state, "engine", None) is not None


@router.get("/health/live")
def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready")
def ready(request: Request, response: Response) -> dict[str, str]:
    if not _engine_ready(request):
        response.status_code = 503
        return {"status": "loading"}
    return {"status": "ok"}


@router.get("/health/startup")
def startup(request: Request, response: Response) -> dict[str, str]:
    if not _engine_ready(request):
        response.status_code = 503
        return {"status": "loading"}
    return {"status": "ok"}


@router.get("/metrics")
def metrics() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
