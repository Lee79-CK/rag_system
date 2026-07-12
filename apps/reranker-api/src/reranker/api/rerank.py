"""POST /internal/v1/rerank — docs/TDD.md §7.4, PRD §17.7.

서비스-내부 계약이므로 요청/응답 모델은 이 앱에 로컬 정의한다.
입력 후보 상한(RERANK_MAX_CANDIDATES) 초과 시 422 + 표준 ErrorResponse.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import ORJSONResponse
from pydantic import BaseModel, Field
from rag_common import new_request_id
from rag_schemas import ErrorDetail, ErrorResponse

from reranker.core.config import get_settings
from reranker.engine import Engine

router = APIRouter(prefix="/internal/v1", tags=["rerank"])


class RerankRequest(BaseModel):
    query: str
    documents: list[str] = Field(default_factory=list)
    top_n: int = Field(default=8, ge=0)


class RerankItem(BaseModel):
    index: int
    score: float


class RerankResponse(BaseModel):
    results: list[RerankItem]
    model: str


@router.post("/rerank", response_model=RerankResponse)
def rerank(payload: RerankRequest, request: Request):
    settings = get_settings()
    max_candidates = settings.rerank_max_candidates
    if len(payload.documents) > max_candidates:
        error = ErrorResponse(
            error=ErrorDetail(
                code="TOO_MANY_CANDIDATES",
                message=(
                    f"재정렬 후보는 최대 {max_candidates}개까지 허용됩니다 "
                    f"(요청 {len(payload.documents)}개)."
                ),
                request_id=new_request_id(),
                detail={"max_candidates": max_candidates, "received": len(payload.documents)},
            )
        )
        return ORJSONResponse(status_code=422, content=error.model_dump())

    engine: Engine = request.app.state.engine
    results = engine.rerank(payload.query, payload.documents, payload.top_n)
    return RerankResponse(
        results=[RerankItem(index=r.index, score=r.score) for r in results],
        model=engine.model_name,
    )
