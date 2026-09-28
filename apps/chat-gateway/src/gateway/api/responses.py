"""공통 응답 헬퍼 — 표준 Error Schema(§3.3)로 변환."""

from __future__ import annotations

from fastapi.responses import ORJSONResponse
from rag_schemas import ErrorDetail, ErrorResponse


def error_response(
    status_code: int,
    code: str,
    message: str,
    request_id: str,
    detail: dict | None = None,
) -> ORJSONResponse:
    """ErrorResponse(§3.3) 본문으로 ORJSONResponse를 만든다. Stack trace 미포함."""
    body = ErrorResponse(
        error=ErrorDetail(code=code, message=message, request_id=request_id, detail=detail)
    )
    return ORJSONResponse(status_code=status_code, content=body.model_dump())


class ApiError(Exception):
    """라우터에서 raise → main 의 exception handler 가 ErrorResponse 로 변환."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(code)
        self.status_code = status_code
        self.code = code
        self.message = message
