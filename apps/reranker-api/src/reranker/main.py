"""reranker-api FastAPI 앱 팩토리 — docs/TDD.md §7.4.

모델 로딩은 lifespan에서 1회. 로딩 완료 전 /health/startup 은 503.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import ORJSONResponse

from reranker.api import health, rerank
from reranker.core.config import get_settings
from reranker.engine import build_engine

try:
    from rag_observability import configure_logging, get_logger
except ImportError:  # pragma: no cover - observability 는 워크스페이스 필수 의존성

    def configure_logging(service_name: str, **_: object) -> None:  # type: ignore[misc]
        return None

    def get_logger(name: str | None = None):  # type: ignore[misc]
        import logging

        return logging.getLogger(name)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    log = get_logger("reranker")
    settings = get_settings()
    # 로딩 완료 전에는 engine 미설정 → /health/startup 503.
    app.state.engine = None
    log.info("engine_loading", model_path=settings.reranker_model_path, mock=settings.reranker_mock)
    app.state.engine = build_engine(settings)
    log.info("engine_ready", model=app.state.engine.model_name)
    yield


def create_app() -> FastAPI:
    configure_logging("reranker")
    app = FastAPI(
        title="reranker-api",
        version="0.1.0",
        default_response_class=ORJSONResponse,
        lifespan=lifespan,
    )
    app.include_router(health.router)
    app.include_router(rerank.router)
    return app


app = create_app()
