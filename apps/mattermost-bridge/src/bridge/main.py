"""mattermost-bridge FastAPI 앱 (docs/TDD.md §7.1)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import ORJSONResponse
from rag_observability import configure_logging

from bridge.api import actions, health, outgoing


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    configure_logging("mattermost-bridge")
    yield


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
