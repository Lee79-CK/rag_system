"""mattermost-bridge FastAPI 앱 (docs/TDD.md §7.1)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import ORJSONResponse
from rag_observability import configure_logging, get_logger

from bridge.api import actions, health, outgoing
from bridge.core.config import get_settings


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    configure_logging("mattermost-bridge")
    _warn_missing_secrets()
    yield


def _warn_missing_secrets() -> None:
    """Secret 파일이 비어 있으면 기동 시 1회 경고한다. 런타임은 fail-closed 로 전부 거부된다 (§11 #1)."""
    log = get_logger("bridge.startup")
    settings = get_settings()
    if not settings.outgoing_token():
        log.error(
            "startup.outgoing_token_missing", file=settings.mattermost_outgoing_token_secret_file
        )
    if not settings.feedback_signing_key():
        log.error("startup.feedback_signing_key_missing", file=settings.feedback_signing_key_file)


def create_app() -> FastAPI:
    app = FastAPI(
        title="mattermost-bridge",
        default_response_class=ORJSONResponse,
        lifespan=_lifespan,
    )
    app.include_router(health.router)
    app.include_router(outgoing.router)
    app.include_router(actions.router)
    return app


app = create_app()
