"""admin-api FastAPI 애플리케이션 팩토리 — docs/TDD.md §7.5.

- create_app() 팩토리, default_response_class=ORJSONResponse
- lifespan에서 configure_logging("admin-api")
- {data, meta} 응답 envelope (admin.api.responses.envelope)
- 표준 Error Schema(§3.3) 예외 핸들러
- 감사 로그 미들웨어(§7.5, FR-AUTH-005)
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import ORJSONResponse
from rag_common import new_request_id
from rag_observability import configure_logging, get_logger
from rag_schemas import ErrorDetail, ErrorResponse

from admin.api import (
    auth,
    channels,
    chat_jobs,
    chat_users,
    documents,
    errors,
    evaluation,
    feedback,
    health,
    settings,
)
from admin.core.audit import AuditMiddleware
from admin.core.config import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = get_settings()
    configure_logging("admin-api", level=cfg.log_level)
    get_logger("admin-api").info("admin_api_startup", app_env=cfg.app_env)
    yield


def _error_response(code: str, message: str, http_status: int) -> ORJSONResponse:
    body = ErrorResponse(error=ErrorDetail(code=code, message=message, request_id=new_request_id()))
    return ORJSONResponse(status_code=http_status, content=body.model_dump())


def create_app() -> FastAPI:
    app = FastAPI(
        title="admin-api",
        description="문서/Channel/설정/피드백 관리 Backend (docs/TDD.md §7.5)",
        version="0.1.0",
        default_response_class=ORJSONResponse,
        lifespan=lifespan,
    )

    app.add_middleware(AuditMiddleware)

    @app.exception_handler(HTTPException)
    async def _http_exc(request: Request, exc: HTTPException) -> ORJSONResponse:
        # api_error()가 만든 detail은 이미 ErrorResponse 형태.
        if isinstance(exc.detail, dict) and "error" in exc.detail:
            return ORJSONResponse(status_code=exc.status_code, content=exc.detail)
        return _error_response("HTTP_ERROR", str(exc.detail), exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def _validation_exc(request: Request, exc: RequestValidationError) -> ORJSONResponse:
        return _error_response("VALIDATION_ERROR", "요청 검증에 실패했습니다.", 422)

    @app.exception_handler(Exception)
    async def _unhandled_exc(request: Request, exc: Exception) -> ORJSONResponse:
        # Stack trace를 응답에 포함하지 않는다 (§3.2 MUST).
        get_logger("admin-api").error("unhandled_error", error=type(exc).__name__)
        return _error_response("INTERNAL_ERROR", "내부 오류가 발생했습니다.", 500)

    for module in (
        health,
        auth,
        documents,
        channels,
        chat_users,
        chat_jobs,
        settings,
        evaluation,
        feedback,
        errors,
    ):
        app.include_router(module.router)

    return app


app = create_app()
