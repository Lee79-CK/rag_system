"""embedding-api HTTP 클라이언트 (EmbeddingPort 구현). POST /internal/v1/embeddings.

검색 질의 전용 → input_type="query" (비대칭 모델의 질의 접두어 적용, 가이드 §5.1.2).
"""

from __future__ import annotations

import httpx


class EmbeddingClient:
    def __init__(self, base_url: str, *, connect_timeout: float = 3.0, read_timeout: float = 10.0):
        self._base = base_url.rstrip("/")
        self._timeout = httpx.Timeout(
            connect=connect_timeout, read=read_timeout, write=read_timeout, pool=read_timeout
        )

    async def embed(self, texts: list[str]) -> list[list[float]]:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(
                f"{self._base}/internal/v1/embeddings",
                json={"texts": texts, "normalize": True, "input_type": "query"},
            )
            resp.raise_for_status()
            return resp.json()["embeddings"]
