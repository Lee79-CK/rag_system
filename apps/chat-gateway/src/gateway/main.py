"""chat-gateway ASGI 앱 (docs/TDD.md §7.1).

`gateway.main:app` = socket.io(`/ws`) + FastAPI(REST) 결합 ASGI 앱.
테스트는 `create_app()`(FastAPI 단독) + dependency_overrides 를 사용한다.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from chat_adapter import StreamEmitter
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import ORJSONResponse
from rag_common import new_request_id
from rag_observability import configure_logging

from gateway.api import actions, auth, channels, health, posts
from gateway.api.responses import ApiError, error_response


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    configure_logging("chat-gateway")
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="chat-gateway",
        default_response_class=ORJSONResponse,
        lifespan=_lifespan,
    )

    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError) -> ORJSONResponse:
        return error_response(exc.status_code, exc.code, exc.message, new_request_id())

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> ORJSONResponse:
        # 입력값 원문(ctx/input)은 응답에 싣지 않는다 — 필드 위치만 전달
        fields = [".".join(str(p) for p in e.get("loc", ())) for e in exc.errors()]
        return error_response(
            400,
            "VALIDATION_ERROR",
            "요청 형식이 올바르지 않습니다.",
            new_request_id(),
            detail={"fields": fields},
        )

    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(channels.router)
    app.include_router(posts.router)
    app.include_router(actions.router)
    return app


def create_asgi(fastapi_app: FastAPI | None = None) -> Any:
    """REST + socket.io 결합. Emitter 는 AsyncServer(Redis manager) 로 구성한다."""
    import socketio

    from gateway.core.config import get_settings
    from gateway.deps import provide_store, set_emitter
    from gateway.realtime import RealtimeHub, build_socket_server

    fastapi_app = fastapi_app or create_app()
    sio = build_socket_server(get_settings())
    RealtimeHub(sio, settings=get_settings, store=provide_store)
    set_emitter(StreamEmitter(sio))
    return socketio.ASGIApp(sio, other_asgi_app=fastapi_app, socketio_path="ws")


app = create_asgi()
