"""Health/metrics 엔드포인트 (§17.10)."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

router = APIRouter()


@router.get("/health/live")
async def live() -> dict:
    return {"status": "ok"}


@router.get("/health/ready")
async def ready(request: Request, response: Response) -> dict:
    if getattr(request.app.state, "ready", False):
        return {"status": "ok"}
    response.status_code = 503
    return {"status": "starting"}


@router.get("/health/startup")
async def startup(request: Request, response: Response) -> dict:
    if getattr(request.app.state, "ready", False):
        return {"status": "ok"}
    response.status_code = 503
    return {"status": "starting"}


@router.get("/metrics")
async def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
