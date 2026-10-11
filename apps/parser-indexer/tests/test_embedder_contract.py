"""parser-indexer ↔ embedding-api 요청 계약 (PRD §17.6: 요청 키는 `texts`).

리뷰에서 `input` 키로 보내던 버그가 발견되었다 — 서버가 `texts` 기본값 [] 로 200 을 돌려
색인이 항상 EMBEDDING 단계에서 실패했다. 이 테스트는 실제 HTTP 직렬화 경계를 고정한다.
"""

from __future__ import annotations

import json

import httpx
from ingestion.indexer.embedder import Embedder


def test_fr_idx_004_embedder_sends_texts_key():
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append(body)
        return httpx.Response(200, json={"embeddings": [[0.0] * 4 for _ in body["texts"]]})

    client = httpx.Client(base_url="http://embedding", transport=httpx.MockTransport(handler))
    embedder = Embedder("http://embedding", batch_size=2, client=client)
    progress: list[tuple[int, int]] = []
    vectors = embedder.embed(["a", "b", "c"], on_progress=lambda d, t: progress.append((d, t)))

    assert len(vectors) == 3
    assert progress == [(2, 3), (3, 3)]  # batch 마다 누적 완료 수
    assert [b["texts"] for b in seen] == [["a", "b"], ["c"]]
    assert all("input" not in b for b in seen)
    assert all(b["normalize"] is True for b in seen)


def test_embedder_raises_on_count_mismatch():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"embeddings": []})  # 서버가 요청 키를 무시한 상황

    client = httpx.Client(base_url="http://embedding", transport=httpx.MockTransport(handler))
    embedder = Embedder("http://embedding", client=client)
    try:
        embedder.embed(["a"])
    except ValueError as exc:
        assert "불일치" in str(exc)
    else:
        raise AssertionError("count mismatch must raise")
