"""Web Chat 채널/Binding/멤버 관리 테스트 — §7.5, FR-OPS-00x (Channel 격리 경계)."""

from __future__ import annotations

from admin.db.models import ChatUser


def _create_channel(client, auth, name: str = "rag-cloud-ops") -> str:
    ch = client.post(
        "/api/v1/chat/channels",
        json={"name": name, "display_name": "Cloud 운영 Q&A", "purpose": "운영 문서 질의"},
        headers=auth("sysadmin"),
    )
    assert ch.status_code == 201, ch.text
    return ch.json()["data"]["id"]


def _create_binding(client, auth, channel_id: str, **over) -> str:
    body = {"enabled": True, **over}
    b = client.post(
        f"/api/v1/chat/channels/{channel_id}/bindings", json=body, headers=auth("sysadmin")
    )
    assert b.status_code == 201, b.text
    return b.json()["data"]["id"]


def test_channel_create_and_duplicate_name(client, seed, auth):
    seed({"sysadmin": ["SYS_ADMIN"]})
    _create_channel(client, auth)
    dup = client.post(
        "/api/v1/chat/channels",
        json={"name": "rag-cloud-ops", "display_name": "x"},
        headers=auth("sysadmin"),
    )
    assert dup.status_code == 409
    bad = client.post(
        "/api/v1/chat/channels",
        json={"name": "Bad Name!", "display_name": "x"},
        headers=auth("sysadmin"),
    )
    assert bad.status_code == 422


def test_binding_has_no_secret_fields(client, seed, auth):
    """Mattermost 시절 secret_ref(Incoming Webhook) 개념은 완전히 제거되었다."""
    seed({"sysadmin": ["SYS_ADMIN"]})
    channel_id = _create_channel(client, auth)
    _create_binding(client, auth, channel_id)
    got = client.get(f"/api/v1/chat/channels/{channel_id}", headers=auth("sysadmin"))
    assert got.status_code == 200
    assert "secret" not in got.text.lower() and "webhook" not in got.text.lower()
    assert got.json()["data"]["bindings"][0]["mode"] == "DEDICATED_CHANNEL"


def test_trigger_word_mode_requires_trigger(client, seed, auth):
    seed({"sysadmin": ["SYS_ADMIN"]})
    channel_id = _create_channel(client, auth)
    r = client.post(
        f"/api/v1/chat/channels/{channel_id}/bindings",
        json={"mode": "TRIGGER_WORD"},
        headers=auth("sysadmin"),
    )
    assert r.status_code == 422
    _create_binding(client, auth, channel_id, mode="TRIGGER_WORD", trigger_word="!rag")


def test_fr_chat_014_binding_direct_llm_flag(client, seed, auth):
    """`/` 직접 대화는 기본 꺼짐 — 관리자가 채널별로 켠다."""
    seed({"sysadmin": ["SYS_ADMIN"]})
    channel_id = _create_channel(client, auth)
    binding_id = _create_binding(client, auth, channel_id)
    got = client.get(f"/api/v1/chat/channels/{channel_id}", headers=auth("sysadmin"))
    assert got.json()["data"]["bindings"][0]["direct_llm_enabled"] is False

    upd = client.put(
        f"/api/v1/chat/bindings/{binding_id}",
        json={"direct_llm_enabled": True},
        headers=auth("sysadmin"),
    )
    assert upd.status_code == 200, upd.text
    assert upd.json()["data"]["direct_llm_enabled"] is True


def test_binding_enable_disable(client, seed, auth):
    seed({"sysadmin": ["SYS_ADMIN"]})
    channel_id = _create_channel(client, auth)
    binding_id = _create_binding(client, auth, channel_id)

    dis = client.post(f"/api/v1/chat/bindings/{binding_id}/disable", headers=auth("sysadmin"))
    assert dis.status_code == 200
    assert dis.json()["data"]["enabled"] is False

    en = client.post(f"/api/v1/chat/bindings/{binding_id}/enable", headers=auth("sysadmin"))
    assert en.status_code == 200
    assert en.json()["data"]["enabled"] is True


def test_members_add_list_remove(client, seed, auth, TestSession):
    seed({"sysadmin": ["SYS_ADMIN"]})
    channel_id = _create_channel(client, auth)
    with TestSession() as s:
        u = ChatUser(email="hong@example.com", display_name="홍길동")
        bot = ChatUser(email="bot@local", display_name="RAG Assistant", is_bot=True)
        s.add_all([u, bot])
        s.commit()
        uid, bot_id = str(u.id), str(bot.id)

    add = client.post(
        f"/api/v1/chat/channels/{channel_id}/members",
        json={"user_ids": [uid]},
        headers=auth("sysadmin"),
    )
    assert add.status_code == 201 and add.json()["data"]["added"] == 1
    # Bot 계정은 멤버로 추가할 수 없다 (답변은 binding 으로만)
    assert (
        client.post(
            f"/api/v1/chat/channels/{channel_id}/members",
            json={"user_ids": [bot_id]},
            headers=auth("sysadmin"),
        ).status_code
        == 404
    )
    members = client.get(
        f"/api/v1/chat/channels/{channel_id}/members", headers=auth("sysadmin")
    ).json()["data"]
    assert [m["email"] for m in members] == ["hong@example.com"]
    rm = client.delete(
        f"/api/v1/chat/channels/{channel_id}/members/{uid}", headers=auth("sysadmin")
    )
    assert rm.status_code == 200


def test_channel_api_write_requires_sys_admin_read_allows_doc_admin(client, seed, auth):
    """조회는 DOC_ADMIN 허용(문서 허용 채널 선택·채널 관리 읽기 전용 화면), 쓰기는 SYS_ADMIN 만."""
    seed({"sysadmin": ["SYS_ADMIN"], "docadmin": ["DOC_ADMIN"], "auditor": ["AUDITOR"]})
    cid = _create_channel(client, auth)
    assert client.get("/api/v1/chat/channels", headers=auth("docadmin")).status_code == 200
    assert client.get(f"/api/v1/chat/channels/{cid}", headers=auth("docadmin")).status_code == 200
    assert client.get("/api/v1/chat/channels", headers=auth("auditor")).status_code == 403
    created = client.post(
        "/api/v1/chat/channels",
        json={"name": "doc-made", "display_name": "x"},
        headers=auth("docadmin"),
    )
    assert created.status_code == 403
    assert (
        client.post(
            f"/api/v1/chat/channels/{cid}/bindings", json={}, headers=auth("docadmin")
        ).status_code
        == 403
    )


def test_channel_list_includes_bindings_and_member_count(client, seed, auth, TestSession):
    """목록이 binding 을 빼면 admin-web 이 RAG 스위치 대신 [+ Binding] 을 그려 중복 생성을 유도한다."""
    from admin.db.models import ChatChannelMember, ChatUser

    seed({"sysadmin": ["SYS_ADMIN"]})
    with_binding = _create_channel(client, auth, "rag-cloud-ops")
    bid = _create_binding(client, auth, with_binding)
    without = _create_channel(client, auth, "rag-empty")
    with TestSession() as s:
        u = ChatUser(email="m@example.com", display_name="m", password_hash="x")
        s.add(u)
        s.flush()
        s.add(ChatChannelMember(channel_id=__import__("uuid").UUID(with_binding), user_id=u.id))
        s.commit()

    rows = {
        c["id"]: c
        for c in client.get("/api/v1/chat/channels", headers=auth("sysadmin")).json()["data"]
    }
    assert [b["id"] for b in rows[with_binding]["bindings"]] == [bid]
    assert rows[with_binding]["member_count"] == 1
    assert rows[without]["bindings"] == [] and rows[without]["member_count"] == 0
