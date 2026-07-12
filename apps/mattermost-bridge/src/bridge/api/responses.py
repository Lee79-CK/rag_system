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


def ignore_response() -> ORJSONResponse:
    """무시성 이벤트 — Mattermost가 오류로 취급하지 않도록 200 + 빈 본문 (§3.3 note)."""
    return ORJSONResponse(status_code=200, content={})


def text_response(text: str) -> ORJSONResponse:
    """Mattermost Channel에 안내 text를 게시하는 200 응답."""
    return ORJSONResponse(status_code=200, content={"text": text})
