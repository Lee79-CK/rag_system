"""reranker-api HTTP 클라이언트 (RerankPort 구현). POST /internal/v1/rerank."""

from __future__ import annotations

import httpx


class RerankerClient:
    def __init__(self, base_url: str, *, connect_timeout: float = 3.0, read_timeout: float = 10.0):
        self._base = base_url.rstrip("/")
        self._timeout = httpx.Timeout(
            connect=connect_timeout, read=read_timeout, write=read_timeout, pool=read_timeout
        )

    async def rerank(self, query: str, documents: list[str], top_n: int) -> list[tuple[int, float]]:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(
                f"{self._base}/internal/v1/rerank",
                json={"query": query, "documents": documents, "top_n": top_n},
            )
            resp.raise_for_status()
            return [(r["index"], r["score"]) for r in resp.json()["results"]]
