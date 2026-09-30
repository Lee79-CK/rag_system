"""POST /internal/v1/embeddings — docs/TDD.md §7.3, PRD §17.6.

서비스-내부 계약이므로 요청/응답 모델은 이 앱에 로컬 정의한다
(libs/schemas 에는 embedding 스키마가 없다).
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from embedding.engine import EMBEDDING_DIM, Engine

router = APIRouter(prefix="/internal/v1", tags=["embeddings"])


class EmbeddingRequest(BaseModel):
    # 필수 키. 기본값을 두면 호출자의 키 오타(예: `input`)가 200 + 빈 결과로 묻힌다 (FR-IDX-004).
    texts: list[str] = Field(...)
    normalize: bool = True
    # 검색 질의(rag-api)는 "query", 색인 청크(parser-indexer)는 기본 "passage".
    # EMBEDDING_QUERY_PREFIX/PASSAGE_PREFIX 가 비어 있으면(bge-m3·KURE-v1) 결과 동일.
    input_type: Literal["query", "passage"] = "passage"


class Usage(BaseModel):
    count: int


class EmbeddingResponse(BaseModel):
    embeddings: list[list[float]]
    model: str
    dim: int = EMBEDDING_DIM
    usage: Usage


@router.post("/embeddings", response_model=EmbeddingResponse)
def create_embeddings(payload: EmbeddingRequest, request: Request) -> EmbeddingResponse:
    engine: Engine = request.app.state.engine
    vectors = engine.embed(
        payload.texts, normalize=payload.normalize, input_type=payload.input_type
    )
    return EmbeddingResponse(
        embeddings=vectors,
        model=engine.model_name,
        dim=engine.dim,
        usage=Usage(count=len(vectors)),
    )
