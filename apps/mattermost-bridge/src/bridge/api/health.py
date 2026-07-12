"""Health / Metrics endpoint (docs/TDD.md §17.10)."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Response
from fastapi.responses import ORJSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from bridge.deps import provide_redis

router = APIRouter()


@router.get("/health/live")
async def live() -> ORJSONResponse:
    return ORJSONResponse({"status": "ok"})


@router.get("/health/startup")
async def startup() -> ORJSONResponse:
    return ORJSONResponse({"status": "ok"})


@router.get("/health/ready")
async def ready(redis: Annotated[Any, Depends(provide_redis)]) -> ORJSONResponse:
    """Redis 도달 가능하면 200, 아니면 503."""
    try:
        await redis.ping()
    except Exception:
        return ORJSONResponse({"status": "unavailable"}, status_code=503)
    return ORJSONResponse({"status": "ok"})


@router.get("/metrics")
async def metrics() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
