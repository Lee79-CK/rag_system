"""표준 Error Schema — docs/TDD.md §3.3."""

from __future__ import annotations

from pydantic import BaseModel


class ErrorDetail(BaseModel):
    code: str  # 예: "UNAUTHORIZED", "CHANNEL_NOT_FOUND", "RATE_LIMITED"
    message: str  # 사용자/운영자용 한국어 메시지
    request_id: str
    detail: dict | None = None  # 민감정보 금지


class ErrorResponse(BaseModel):
    error: ErrorDetail
