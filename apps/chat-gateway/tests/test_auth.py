"""인증 테스트 (docs/TDD.md §7.1.5, FR-WEB-001~003)."""

from __future__ import annotations

import time

from conftest import PASSWORD, SLUG
from gateway.core.config import REFRESH_COOKIE
from rag_common.passwords import compute_prehash


def test_fr_web_001_login_prehash_ok(harness):
    resp = harness.client.post("/api/v1/auth/login", json=harness.login_body("Alice@Example.com"))
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["user"]["id"] == harness.alice.id
    assert data["expires_in"] == harness.settings.chat_access_ttl_seconds
    # refresh 는 HttpOnly 쿠키로만 (본문에 없음)
    assert "refresh" not in resp.text
    cookie = resp.headers["set-cookie"]
    assert REFRESH_COOKIE in cookie and "HttpOnly" in cookie and "SameSite=strict" in cookie
    me = harness.client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {data['access_token']}"}
    )
    assert me.json()["email"] == "alice@example.com"


def test_fr_web_001_login_invalid_401(harness):
    wrong = harness.client.post(
        "/api/v1/auth/login", json=harness.login_body("alice@example.com", "Wrong!Password99")
    )
    unknown = harness.client.post("/api/v1/auth/login", json=harness.login_body("nobody@x.io"))
    assert wrong.status_code == unknown.status_code == 401
    # 사용자 존재 여부를 구분할 수 없는 동일 응답 (열거 방지)
    assert wrong.json()["error"]["message"] == unknown.json()["error"]["message"]


def test_login_bot_account_rejected(harness):
    body = harness.login_body("rag-bot@local")
    assert harness.client.post("/api/v1/auth/login", json=body).status_code == 401


def test_login_replay_nonce_rejected(harness):
    body = harness.login_body("alice@example.com")
    assert harness.client.post("/api/v1/auth/login", json=body).status_code == 200
    assert harness.client.post("/api/v1/auth/login", json=body).status_code == 400
    stale = harness.login_body("alice@example.com", timestamp=int(time.time() * 1000) - 3_600_000)
    assert harness.client.post("/api/v1/auth/login", json=stale).status_code == 400


def test_fr_web_002_refresh_rotation(harness):
    harness.client.post("/api/v1/auth/login", json=harness.login_body("alice@example.com"))
    first = harness.client.cookies.get(REFRESH_COOKIE)
    r1 = harness.client.post("/api/v1/auth/refresh")
    assert r1.status_code == 200 and r1.json()["user"]["id"] == harness.alice.id
    second = harness.client.cookies.get(REFRESH_COOKIE)
    assert second and second != first
    # 이미 사용된(rotation 된) refresh 토큰 재사용 불가
    harness.client.cookies.set(REFRESH_COOKIE, first, path="/api/v1/auth")
    assert harness.client.post("/api/v1/auth/refresh").status_code == 401


def test_fr_web_003_logout_revokes_refresh(harness):
    harness.client.post("/api/v1/auth/login", json=harness.login_body("alice@example.com"))
    token = harness.client.cookies.get(REFRESH_COOKIE)
    assert harness.client.post("/api/v1/auth/logout").status_code == 204
    harness.client.cookies.set(REFRESH_COOKIE, token, path="/api/v1/auth")
    assert harness.client.post("/api/v1/auth/refresh").status_code == 401


def test_protected_endpoints_require_bearer(harness):
    assert harness.client.get("/api/v1/channels/sidebar").status_code == 401
    bad = {"Authorization": "Bearer not-a-jwt"}
    assert harness.client.get("/api/v1/channels/sidebar", headers=bad).status_code == 401


def test_password_change_policy_and_success(harness):
    email = "alice@example.com"
    cur = compute_prehash(SLUG, email, PASSWORD, iterations=1000)
    new = compute_prehash(SLUG, email, "N3w!Password#2026", iterations=1000)
    weak = harness.client.post(
        "/api/v1/auth/password/change",
        headers=harness.auth(),
        json={"current_prehash": cur, "new_prehash": new, "policy": {"length": 6, "kinds": 1}},
    )
    assert weak.status_code == 400 and weak.json()["error"]["code"] == "PASSWORD_POLICY"
    ok = harness.client.post(
        "/api/v1/auth/password/change",
        headers=harness.auth(),
        json={"current_prehash": cur, "new_prehash": new, "policy": {"length": 17, "kinds": 4}},
    )
    assert ok.status_code == 204
    relogin = harness.login_body(email, "N3w!Password#2026")
    assert harness.client.post("/api/v1/auth/login", json=relogin).status_code == 200
