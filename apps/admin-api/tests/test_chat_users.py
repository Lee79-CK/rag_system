"""Web Chat 사용자 관리 테스트 — 임시 비밀번호 1회 노출, 해시 비노출, 로그인 호환."""

from __future__ import annotations

import pytest
from admin.core.config import get_settings
from admin.db.models import ChatUser
from rag_common.passwords import compute_prehash, verify_prehash

PEPPER = "admin-test-pepper-0123456789"


@pytest.fixture
def pepper(tmp_path, monkeypatch):
    f = tmp_path / "pepper"
    f.write_text(PEPPER)
    monkeypatch.setenv("PASSWORD_PEPPER_FILE", str(f))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_create_user_returns_temp_password_once(client, seed, auth, pepper, TestSession):
    seed({"sysadmin": ["SYS_ADMIN"]})
    r = client.post(
        "/api/v1/chat/users",
        json={"email": "Hong@Example.com", "display_name": "홍길동"},
        headers=auth("sysadmin"),
    )
    assert r.status_code == 201, r.text
    data = r.json()["data"]
    temp = data["temporary_password"]
    assert data["email"] == "hong@example.com" and data["must_change_password"] is True
    assert "password_hash" not in r.text

    # 이후 조회 응답에는 임시 비밀번호/해시가 없다
    listed = client.get("/api/v1/chat/users", headers=auth("sysadmin"))
    assert temp not in listed.text and "password_hash" not in listed.text

    # chat-gateway 로그인과 동일 검증식으로 통과해야 한다 (브라우저 prehash 호환)
    with TestSession() as s:
        u = s.query(ChatUser).filter_by(email="hong@example.com").one()
        pre = compute_prehash(get_settings().chat_workspace_slug, "hong@example.com", temp)
        assert verify_prehash(u.password_hash, pre, PEPPER.encode())


def test_duplicate_email_conflict(client, seed, auth, pepper):
    seed({"sysadmin": ["SYS_ADMIN"]})
    body = {"email": "a@b.co", "display_name": "A"}
    assert client.post("/api/v1/chat/users", json=body, headers=auth("sysadmin")).status_code == 201
    assert client.post("/api/v1/chat/users", json=body, headers=auth("sysadmin")).status_code == 409


def test_reset_password_rotates_hash(client, seed, auth, pepper, TestSession):
    seed({"sysadmin": ["SYS_ADMIN"]})
    uid = client.post(
        "/api/v1/chat/users",
        json={"email": "a@b.co", "display_name": "A"},
        headers=auth("sysadmin"),
    ).json()["data"]["id"]
    with TestSession() as s:
        before = s.get(ChatUser, __import__("uuid").UUID(uid)).password_hash
    r = client.post(f"/api/v1/chat/users/{uid}/reset-password", headers=auth("sysadmin"))
    assert r.status_code == 200 and r.json()["data"]["temporary_password"]
    with TestSession() as s:
        assert s.get(ChatUser, __import__("uuid").UUID(uid)).password_hash != before


def test_create_user_without_pepper_503(client, seed, auth, monkeypatch):
    monkeypatch.setenv("PASSWORD_PEPPER_FILE", "")
    get_settings.cache_clear()
    seed({"sysadmin": ["SYS_ADMIN"]})
    r = client.post(
        "/api/v1/chat/users",
        json={"email": "a@b.co", "display_name": "A"},
        headers=auth("sysadmin"),
    )
    assert r.status_code == 503
    get_settings.cache_clear()
