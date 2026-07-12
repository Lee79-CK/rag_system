"""health 엔드포인트 테스트 — docs/TDD.md §17.10."""

from __future__ import annotations

from fastapi.testclient import TestClient
from reranker.main import create_app


def test_live_always_ok() -> None:
    client = TestClient(create_app())
    assert client.get("/health/live").status_code == 200


def test_startup_503_before_load_then_200() -> None:
    app = create_app()
    pre = TestClient(app).get("/health/startup")
    assert pre.status_code == 503
    with TestClient(app) as client:
        assert client.get("/health/startup").status_code == 200
        assert client.get("/health/ready").status_code == 200


def test_ready_503_before_load() -> None:
    app = create_app()
    assert TestClient(app).get("/health/ready").status_code == 503


def test_metrics_exposed() -> None:
    with TestClient(create_app()) as client:
        resp = client.get("/metrics")
    assert resp.status_code == 200
