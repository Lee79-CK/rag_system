"""rag-api FastAPI app factory (§7.2). 동기 completions + health."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import ORJSONResponse
from rag_observability import configure_logging
from sqlalchemy import create_engine

from rag.adapters.pg_repo import PgBindingReader
from rag.api import completions, health
from rag.core.config import get_settings
from rag.worker.bootstrap import build_pipeline


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging("rag-api")
    settings = get_settings()
    app.state.settings = settings
    app.state.pipeline = build_pipeline(settings)
    try:
        engine = create_engine(settings.sqlalchemy_url, pool_pre_ping=True)
        app.state.binding_reader = PgBindingReader(engine)
    except Exception:  # noqa: BLE001 — 로컬 DB 부재 시에도 앱 기동 (ready=False로 표기)
        app.state.binding_reader = None
    app.state.ready = app.state.binding_reader is not None
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="rag-api",
        default_response_class=ORJSONResponse,
        lifespan=lifespan,
    )
    app.include_router(health.router)
    app.include_router(completions.router)
    return app


app = create_app()
