"""동기 RAG Completion (테스트/평가용) — POST /internal/v1/rag/completions (§9).

운영 경로는 Queue+Worker다. 이 엔드포인트는 영속화/게시 없이 파이프라인 결과만 반환한다.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from rag_schemas import RagCompletion

from rag.domain.citation import build_citations

router = APIRouter()


class RagCompletionRequest(BaseModel):
    channel_id: str
    message: str
    history: list[tuple[str, str]] = Field(default_factory=list)


@router.post("/internal/v1/rag/completions", response_model=RagCompletion)
async def completions(body: RagCompletionRequest, request: Request) -> RagCompletion:
    binding_reader = request.app.state.binding_reader
    pipeline = request.app.state.pipeline

    binding = binding_reader.get_binding(body.channel_id)
    if binding is None:
        raise HTTPException(status_code=403, detail="CHANNEL_NOT_BOUND")

    output = await pipeline.run(question=body.message, binding=binding, history=body.history)
    return RagCompletion(
        message_id="",  # 동기 경로는 영속화하지 않음
        answer=output.answer,
        citations=output.citations,
        insufficient_evidence=output.insufficient_evidence,
        retrieved=build_citations(output.selected_chunks),  # 평가 Recall@10 용 (인용 여부 무관)
        usage=output.usage,
    )
