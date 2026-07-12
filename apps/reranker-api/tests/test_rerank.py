"""reranker-api 계약 테스트 (mock 엔진) — docs/TDD.md §7.4."""

from __future__ import annotations

from fastapi.testclient import TestClient
from reranker.main import create_app

URL = "/internal/v1/rerank"

_DOCS = [
    "고양이는 포유류 동물이다",
    "파이썬은 프로그래밍 언어이다",
    "고양이 프로그래밍 언어는 없다",
    "날씨가 맑고 화창하다",
]


def _client() -> TestClient:
    return TestClient(create_app())


def test_results_sorted_desc() -> None:
    with _client() as client:
        resp = client.post(
            URL, json={"query": "고양이 동물", "documents": _DOCS, "top_n": len(_DOCS)}
        )
    assert resp.status_code == 200
    scores = [r["score"] for r in resp.json()["results"]]
    assert scores == sorted(scores, reverse=True)


def test_top_n_limits_count() -> None:
    with _client() as client:
        resp = client.post(URL, json={"query": "고양이", "documents": _DOCS, "top_n": 2})
    assert resp.status_code == 200
    assert len(resp.json()["results"]) == 2


def test_indices_map_to_original_positions() -> None:
    with _client() as client:
        resp = client.post(
            URL, json={"query": "파이썬 프로그래밍 언어", "documents": _DOCS, "top_n": 4}
        )
    results = resp.json()["results"]
    # 인덱스는 원본 문서 위치를 가리켜야 하며 유효 범위 내여야 한다.
    indices = [r["index"] for r in results]
    assert all(0 <= i < len(_DOCS) for i in indices)
    assert len(set(indices)) == len(indices)
    # 최상위는 쿼리와 어휘 중첩이 가장 큰 문서(index 1: "파이썬은 프로그래밍 언어이다").
    assert results[0]["index"] == 1


def test_too_many_candidates_returns_422() -> None:
    docs = [f"doc-{i}" for i in range(51)]  # > RERANK_MAX_CANDIDATES (50)
    with _client() as client:
        resp = client.post(URL, json={"query": "q", "documents": docs, "top_n": 5})
    assert resp.status_code == 422
    body = resp.json()
    assert body["error"]["code"] == "TOO_MANY_CANDIDATES"
    assert body["error"]["request_id"]


def test_exactly_max_candidates_ok() -> None:
    docs = [f"doc-{i}" for i in range(50)]
    with _client() as client:
        resp = client.post(URL, json={"query": "q", "documents": docs, "top_n": 5})
    assert resp.status_code == 200
    assert len(resp.json()["results"]) == 5


def test_deterministic() -> None:
    payload = {"query": "고양이 동물", "documents": _DOCS, "top_n": 4}
    with _client() as client:
        r1 = client.post(URL, json=payload)
        r2 = client.post(URL, json=payload)
    assert r1.json()["results"] == r2.json()["results"]


def test_scores_in_unit_interval() -> None:
    with _client() as client:
        resp = client.post(URL, json={"query": "고양이", "documents": _DOCS, "top_n": 4})
    for r in resp.json()["results"]:
        assert 0.0 < r["score"] < 1.0
