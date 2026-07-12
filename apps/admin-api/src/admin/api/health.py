"""Health / metrics 엔드포인트 — docs/TDD.md §17.10.

/health/live, /health/ready(DB 도달성), /health/startup, /metrics(prometheus).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import text
from sqlalchemy.orm import Session

from admin.db.session import get_db

router = APIRouter(tags=["health"])


@router.get("/health/live")
def live() -> dict:
    return {"status": "ok"}


@router.get("/health/startup")
def startup() -> dict:
    return {"status": "ok"}


@router.get("/health/ready")
def ready(response: Response, db: Session = Depends(get_db)) -> dict:
    """DB 도달 가능 여부를 확인한다. 실패 시 503."""
    try:
        db.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001
        response.status_code = 503
        return {"status": "unavailable", "db": False}
    return {"status": "ok", "db": True}


@router.get("/metrics")
def metrics() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
