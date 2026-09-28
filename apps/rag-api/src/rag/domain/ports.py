"""Domain Ports (Protocol). 어댑터는 rag/adapters/* 에서 구현한다.

도메인은 이 인터페이스에만 의존하므로 테스트에서 fake로 교체 가능하다.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
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


@dataclass(slots=True)
class LLMStreamEvent:
    """스트리밍 이벤트 1건. delta(텍스트 조각) 또는 usage(마지막 1회) 중 하나를 채운다."""

    delta: str = ""
    usage: dict[str, Any] | None = None


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

    def stream(
        self, messages: list[dict[str, str]], *, max_tokens: int, temperature: float
    ) -> AsyncIterator[LLMStreamEvent]:
        """토큰 스트리밍 (ADR-001 개정). async generator 로 구현한다."""
        ...
