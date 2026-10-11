"""Embedding API Batch 호출 (docs/TDD.md §7.7 step 6, FR-IDX-005).

- POST {EMBEDDING_API_URL}/internal/v1/embeddings {"texts": [...]}, batch=64.
- 실패 batch만 tenacity(http_retry)로 재시도한다.
- httpx는 명시적 timeout을 사용한다 (§3.2). 런타임 외부 네트워크 호출 없음(내부 API만).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from itertools import batched

import httpx
from rag_common import http_retry
from rag_observability import get_logger

logger = get_logger(__name__)

_EMBEDDINGS_PATH = "/internal/v1/embeddings"


class Embedder:
    """내부 embedding-api 클라이언트. batch 분할 + 실패 batch 재시도."""

    def __init__(
        self,
        base_url: str,
        *,
        batch_size: int = 64,
        timeout: float = 30.0,
        client: httpx.Client | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._batch_size = batch_size
        self._timeout = httpx.Timeout(timeout, connect=min(5.0, timeout))
        self._client = client
        self._owns_client = client is None

    def _get_client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(base_url=self._base_url, timeout=self._timeout)
        return self._client

    def close(self) -> None:
        if self._owns_client and self._client is not None:
            self._client.close()
            self._client = None

    def __enter__(self) -> Embedder:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @http_retry(attempts=3, exceptions=(httpx.HTTPError,))
    def _embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        client = self._get_client()
        resp = client.post(
            _EMBEDDINGS_PATH,
            json={
                "texts": list(texts),
                "normalize": True,
                "input_type": "passage",  # 색인 청크 (질의는 rag-api 가 "query")
            },  # PRD §17.6 계약 (embedding-api EmbeddingRequest)
            timeout=self._timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        return _extract_vectors(data)

    def embed(
        self,
        texts: Sequence[str],
        on_progress: Callable[[int, int], None] | None = None,
    ) -> list[list[float]]:
        """전체 텍스트를 batch로 임베딩. 실패 batch만 재시도한다.

        on_progress(done, total) 는 batch 가 끝날 때마다 호출된다 — CPU 임베딩은 큰 문서에서
        한 시간 넘게 걸리므로 호출자가 진행률을 남겨야 "멈춤"과 구분된다.
        """
        vectors: list[list[float]] = []
        for batch in batched(texts, self._batch_size):
            vectors.extend(self._embed_batch(batch))
            if on_progress is not None:
                on_progress(len(vectors), len(texts))
        if len(vectors) != len(texts):
            raise ValueError(f"임베딩 개수 불일치: got {len(vectors)}, expected {len(texts)}")
        return vectors


def _extract_vectors(data: object) -> list[list[float]]:
    """embedding-api 응답에서 벡터 목록을 추출한다.

    지원 형태:
    - {"data": [{"embedding": [...]}, ...]}   (OpenAI 호환)
    - {"embeddings": [[...], ...]}
    - [[...], ...]
    """
    if isinstance(data, dict):
        if "data" in data and isinstance(data["data"], list):
            return [item["embedding"] for item in data["data"]]
        if "embeddings" in data and isinstance(data["embeddings"], list):
            return list(data["embeddings"])
    if isinstance(data, list):
        return data  # type: ignore[return-value]
    raise ValueError("임베딩 응답 형식을 해석할 수 없음")
