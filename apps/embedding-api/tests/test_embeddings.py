"""embedding-api 계약 테스트 (mock 엔진) — docs/TDD.md §7.3."""

from __future__ import annotations

import math

from embedding.main import create_app
from fastapi.testclient import TestClient

URL = "/internal/v1/embeddings"


def _client() -> TestClient:
    return TestClient(create_app())


def test_embedding_dim_is_1024() -> None:
    with _client() as client:
        resp = client.post(URL, json={"texts": ["안녕하세요", "hello world"]})
    assert resp.status_code == 200
    body = resp.json()
    assert body["dim"] == 1024
    assert body["model"]
    assert body["usage"]["count"] == 2
    assert len(body["embeddings"]) == 2
    assert all(len(v) == 1024 for v in body["embeddings"])


def test_embedding_deterministic() -> None:
    with _client() as client:
        r1 = client.post(URL, json={"texts": ["same text"]})
        r2 = client.post(URL, json={"texts": ["same text"]})
    assert r1.json()["embeddings"][0] == r2.json()["embeddings"][0]


def test_embedding_batch_over_max_handled() -> None:
    texts = [f"doc-{i}" for i in range(150)]  # > EMBEDDING_MAX_BATCH (64)
    with _client() as client:
        resp = client.post(URL, json={"texts": texts})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["embeddings"]) == len(texts)
    assert body["usage"]["count"] == len(texts)


def test_embedding_normalize_produces_unit_vectors() -> None:
    with _client() as client:
        resp = client.post(URL, json={"texts": ["unit vector please"], "normalize": True})
    vec = resp.json()["embeddings"][0]
    norm = math.sqrt(sum(x * x for x in vec))
    assert math.isclose(norm, 1.0, abs_tol=1e-6)


def test_embedding_empty_texts() -> None:
    with _client() as client:
        resp = client.post(URL, json={"texts": []})
    assert resp.status_code == 200
    assert resp.json()["embeddings"] == []
    assert resp.json()["usage"]["count"] == 0
