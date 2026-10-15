"""동기 completions(평가용) — 응답의 retrieved 는 컨텍스트 선택 청크 전체, citations 는 인용분만 (FR-OPS-008)."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from rag.api import completions
from rag.domain.citation import build_citations
from rag.domain.pipeline import PipelineOutput
from rag.domain.ports import ScoredChunk
from rag_schemas import ChannelBinding, ChannelMode, QdrantChunkPayload


def _chunk(i: int, title: str) -> ScoredChunk:
    p = QdrantChunkPayload(
        document_id=f"d{i}",
        document_version_id="v1",
        chunk_id=f"v1-{i:05d}",
        title=title,
        source_file="/data/x.pdf",
        page_start=i,
        chunk_index=i,
        allowed_channel_ids=["c1"],
        content_hash="sha256:x",
        text=f"본문 {i}",
    )
    return ScoredChunk(payload=p, vector_score=0.9, rerank_score=0.9 - i * 0.1)


class _Pipeline:
    async def run(self, *, question, binding, history):
        chunks = [_chunk(1, "A.pdf"), _chunk(2, "B.pdf"), _chunk(3, "C.pdf")]
        return PipelineOutput(
            answer="답 [2]",
            citations=build_citations(chunks, [2]),
            insufficient_evidence=False,
            usage={},
            selected_chunks=chunks,
        )


class _Bindings:
    def get_binding(self, channel_id):
        return ChannelBinding(
            id="b",
            channel_id="c1",
            channel_name="c",
            mode=ChannelMode.DEDICATED_CHANNEL,
            enabled=True,
        )


def test_fr_ops_008_completions_returns_retrieved_chunks_for_recall():
    app = FastAPI()
    app.include_router(completions.router)
    app.state.pipeline = _Pipeline()
    app.state.binding_reader = _Bindings()
    with TestClient(app) as client:
        data = client.post(
            "/internal/v1/rag/completions", json={"channel_id": "c1", "message": "q"}
        ).json()
    assert [c["document_name"] for c in data["citations"]] == ["B.pdf"]
    assert [c["document_name"] for c in data["retrieved"]] == ["A.pdf", "B.pdf", "C.pdf"]
