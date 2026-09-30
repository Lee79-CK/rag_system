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


def test_embedding_missing_texts_key_is_422() -> None:
    """`texts` 는 필수 — 호출자 키 오타(`input`)가 200 + 빈 결과로 묻히면 색인이 조용히 실패한다."""
    with _client() as client:
        resp = client.post(URL, json={"input": ["wrong key"]})
    assert resp.status_code == 422


# ---- 한글 모델 교체 대응 (가이드 §5.1.2) ----


def test_embedding_model_name_follows_model_dir() -> None:
    from embedding.core.config import Settings

    assert Settings(embedding_model_path="/models/embedding/bge-m3").model_name == "bge-m3"
    assert Settings(embedding_model_path="/models/embedding/kure-v1/").model_name == "kure-v1"


def test_embedding_query_prefix_applied_only_to_query() -> None:
    from embedding.core.config import Settings
    from embedding.engine import MockEngine

    plain = MockEngine(Settings(embedding_mock=True))
    arctic = MockEngine(Settings(embedding_mock=True, embedding_query_prefix="query: "))
    text = ["고영향 인공지능의 판단 기준은?"]

    # 접두어 미설정(bge-m3·KURE-v1): query/passage 벡터 동일
    assert plain.embed(text, normalize=True, input_type="query") == plain.embed(
        text, normalize=True
    )
    # 접두어 설정: query 는 "query: " + 텍스트, passage 는 원문 그대로
    assert arctic.embed(text, normalize=True, input_type="query") == plain.embed(
        ["query: " + text[0]], normalize=True
    )
    assert arctic.embed(text, normalize=True, input_type="passage") == plain.embed(
        text, normalize=True
    )


def test_embedding_api_accepts_input_type_and_rejects_unknown() -> None:
    with _client() as client:
        ok = client.post(URL, json={"texts": ["질의"], "input_type": "query"})
        bad = client.post(URL, json={"texts": ["질의"], "input_type": "document"})
    assert ok.status_code == 200
    assert bad.status_code == 422


def test_embedding_real_engine_passes_max_length(monkeypatch, tmp_path) -> None:
    """FlagEmbedding ≥1.3 encode 기본 max_length=512 → 한글 청크 절단. 설정값을 명시 전달해야 한다."""
    import sys
    import types

    import numpy as np
    from embedding.core.config import Settings
    from embedding.engine import RealEngine

    calls: list[dict] = []

    class FakeM3:
        def __init__(self, path: str, **kwargs: object) -> None:
            self.path = path

        def encode(self, texts: list[str], **kwargs: object) -> dict:
            calls.append({"n": len(texts), **kwargs})
            return {"dense_vecs": np.ones((len(texts), 1024))}

    monkeypatch.setitem(sys.modules, "FlagEmbedding", types.SimpleNamespace(BGEM3FlagModel=FakeM3))
    engine = RealEngine(
        Settings(
            embedding_model_path=str(tmp_path), embedding_max_length=2048, embedding_max_batch=2
        )
    )
    vecs = engine.embed(["a", "b", "c"], normalize=True)

    assert len(vecs) == 3
    assert [c["n"] for c in calls] == [2, 1]
    assert all(c["max_length"] == 2048 for c in calls)
    assert all(c["return_sparse"] is False for c in calls)
