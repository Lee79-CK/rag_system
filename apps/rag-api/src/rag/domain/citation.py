"""Citation Trace 생성 (§7.2.1 step12). 사용된 chunk payload → Citation 목록."""

from __future__ import annotations

from rag_schemas import Citation

from rag.domain.ports import ScoredChunk

_EXCERPT_MAX = 200  # Citation.excerpt 최대 200자 (§4.2)


def build_citations(chunks: list[ScoredChunk]) -> list[Citation]:
    citations: list[Citation] = []
    for i, chunk in enumerate(chunks, 1):
        p = chunk.payload
        excerpt = p.text.strip().replace("\n", " ")
        if len(excerpt) > _EXCERPT_MAX:
            excerpt = excerpt[: _EXCERPT_MAX - 1].rstrip() + "…"
        citations.append(
            Citation(
                document_id=p.document_id,
                document_name=p.title,
                page=p.page_start,
                section=p.section,
                excerpt=excerpt,
                score=chunk.rerank_score,
                chunk_id=p.chunk_id,
            )
        )
        _ = i
    return citations
