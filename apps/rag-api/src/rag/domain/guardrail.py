"""근거 부족(Insufficient Evidence) 판정 (§7.2.3, FR-CHAT-004/FR-RAG-010).

발동 조건:
  (a) 검색 결과 0건
  (b) top vector score < SIMILARITY_THRESHOLD
  (c) rerank top score < RERANK_SCORE_THRESHOLD
PoC 확정: 이 경우 LLM을 호출하지 않고 고정 안내문을 게시한다.
"""

from __future__ import annotations

from rag.domain.ports import RetrievedChunk, ScoredChunk


def is_insufficient_after_search(
    retrieved: list[RetrievedChunk], similarity_threshold: float
) -> bool:
    if not retrieved:
        return True
    top = max(c.score for c in retrieved)
    return top < similarity_threshold


def is_insufficient_after_rerank(reranked: list[ScoredChunk], rerank_threshold: float) -> bool:
    if not reranked:
        return True
    top = max(c.rerank_score for c in reranked)
    return top < rerank_threshold
