"""Domain Ports (Protocol). 어댑터는 rag/adapters/* 에서 구현한다.

도메인은 이 인터페이스에만 의존하므로 테스트에서 fake로 교체 가능하다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from rag_schemas import QdrantChunkPayload


@dataclass(slots=True)
class RetrievedChunk:
    """Qdrant 검색 결과 1건 — payload + 유사도 점수."""

    payload: QdrantChunkPayload
    score: float


@dataclass(slots=True)
class ScoredChunk:
    """Re-rank 후 점수가 갱신된 chunk."""

    payload: QdrantChunkPayload
    vector_score: float
    rerank_score: float


@dataclass(slots=True)
class LLMResult:
    text: str
    usage: dict[str, Any] = field(default_factory=dict)


class EmbeddingPort(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class RetrievalPort(Protocol):
    async def search(
        self, query_vector: list[float], qdrant_filter: Any, top_k: int
    ) -> list[RetrievedChunk]: ...


class RerankPort(Protocol):
    async def rerank(self, query: str, documents: list[str], top_n: int) -> list[tuple[int, float]]:
        """(원본 index, score) 목록을 score 내림차순으로 반환."""
        ...


class LLMPort(Protocol):
    async def complete(
        self, messages: list[dict[str, str]], *, max_tokens: int, temperature: float
    ) -> LLMResult: ...
