"""POST /internal/v1/embeddings — docs/TDD.md §7.3, PRD §17.6.

서비스-내부 계약이므로 요청/응답 모델은 이 앱에 로컬 정의한다
(libs/schemas 에는 embedding 스키마가 없다).
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from embedding.engine import EMBEDDING_DIM, Engine

router = APIRouter(prefix="/internal/v1", tags=["embeddings"])


class EmbeddingRequest(BaseModel):
    texts: list[str] = Field(default_factory=list)
    normalize: bool = True


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
    vectors = engine.embed(payload.texts, normalize=payload.normalize)
    return EmbeddingResponse(
        embeddings=vectors,
        model=engine.model_name,
        dim=engine.dim,
        usage=Usage(count=len(vectors)),
    )
