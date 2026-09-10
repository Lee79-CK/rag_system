"""mock-mattermost — Incoming Webhook 수신/조회 계약."""

from __future__ import annotations

from fastapi.testclient import TestClient
from mock_mattermost.server import app


def test_incoming_hook_returns_ok_and_is_listed():
    with TestClient(app) as c:
        c.delete("/posts")
        r = c.post(
            "/hooks/abc",
            json={"channel": "rag-cloud-ops", "text": "답변", "attachments": [{"actions": []}]},
        )
        assert r.status_code == 200 and r.text == "ok"
        posts = c.get("/posts", params={"hook_id": "abc"}).json()
        assert posts["count"] == 1
        assert posts["posts"][0]["text"] == "답변"
        assert c.get("/health/ready").status_code == 200
