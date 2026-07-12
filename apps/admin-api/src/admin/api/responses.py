"""응답 envelope + 표준 에러 helper — docs/TDD.md §7.5, §3.3.

모든 성공 응답은 {"data": ..., "meta": {...}} 형태.
에러는 rag_schemas.ErrorResponse/ErrorDetail 사용.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from rag_common import new_request_id
from rag_schemas import ErrorDetail, ErrorResponse


def envelope(data: Any, **meta: Any) -> dict[str, Any]:
    """성공 응답 envelope 생성."""
    return {"data": data, "meta": meta}


def api_error(code: str, message: str, http_status: int, **detail: Any) -> HTTPException:
    """표준 Error Schema를 담은 HTTPException 생성."""
    body = ErrorResponse(
        error=ErrorDetail(
            code=code,
            message=message,
            request_id=new_request_id(),
            detail=detail or None,
        )
    )
    return HTTPException(status_code=http_status, detail=body.model_dump())
