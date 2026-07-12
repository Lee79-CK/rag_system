"""Qdrant 검색 어댑터 (RetrievalPort 구현). build_filter는 도메인에서 조립되어 주입된다."""

from __future__ import annotations

from typing import Any

from qdrant_client import AsyncQdrantClient
from rag_schemas import QdrantChunkPayload

from rag.domain.ports import RetrievedChunk


class QdrantRepo:
    def __init__(self, url: str, collection: str, *, timeout: float = 5.0):
        self._client = AsyncQdrantClient(url=url, timeout=timeout)
        self._collection = collection

    async def search(
        self, query_vector: list[float], qdrant_filter: Any, top_k: int
    ) -> list[RetrievedChunk]:
        points = await self._client.search(
            collection_name=self._collection,
            query_vector=query_vector,
            query_filter=qdrant_filter,
            limit=top_k,
            with_payload=True,
        )
        out: list[RetrievedChunk] = []
        for p in points:
            payload = QdrantChunkPayload.model_validate(p.payload or {})
            out.append(RetrievedChunk(payload=payload, score=float(p.score)))
        return out

    async def close(self) -> None:
        await self._client.close()
