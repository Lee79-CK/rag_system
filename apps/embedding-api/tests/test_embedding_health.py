"""health 엔드포인트 테스트 — docs/TDD.md §17.10."""

from __future__ import annotations

from embedding.main import create_app
from fastapi.testclient import TestClient


def test_live_always_ok() -> None:
    # lifespan 미실행 상태에서도 live 는 200.
    client = TestClient(create_app())
    assert client.get("/health/live").status_code == 200


def test_startup_503_before_load_then_200() -> None:
    app = create_app()
    # lifespan 진입 전(=엔진 미로딩) → 503.
    pre = TestClient(app).get("/health/startup")
    assert pre.status_code == 503
    # lifespan 진입 후 → 200.
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
    assert "python_info" in resp.text or "process" in resp.text
