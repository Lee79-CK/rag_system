"""질문 수신 파이프라인 테스트 (docs/TDD.md §7.1.3, FR-WEB-004~010)."""

from __future__ import annotations

import logging

from conftest import binding_for
from rag_schemas import ChannelMode, ChatRequest, ConversationMode


def test_fr_web_004_non_member_post_404(harness):
    resp = harness.post("질문", channel_id=harness.other.id)  # alice 는 other 비멤버
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "CHANNEL_NOT_FOUND"
    assert harness.enqueuer.calls == []


def test_fr_web_005_question_creates_bot_placeholder_and_job(harness):
    resp = harness.post("휴가 정책 알려줘")
    assert resp.status_code == 201, resp.text
    user_post = resp.json()
    assert user_post["type"] == "user" and user_post["user"]["id"] == harness.alice.id
    assert len(harness.enqueuer.calls) == 1
    job = harness.store.jobs[0]
    bot_post = harness.store.posts[job["bot_post_id"]]
    assert bot_post.type == "bot" and bot_post.props["streaming"] is True
    # 두 Post 모두 채널 room 으로 post.created
    created = [e for e in harness.sockets.events if e[0] == "post.created"]
    assert [e[2] for e in created] == [f"channel:{harness.channel.id}"] * 2


async def test_fr_web_005_chat_request_stored_for_worker(harness):
    harness.post("휴가 정책 알려줘")
    job = harness.store.jobs[0]
    raw = await harness.redis.get(f"chat:req:{job['id']}")
    req = ChatRequest.model_validate_json(raw)
    assert req.source == "web"
    assert req.channel_id == harness.channel.id
    assert req.bot_post_id == job["bot_post_id"]
    assert req.message == "휴가 정책 알려줘"


def test_fr_web_006_duplicate_client_id_single_job(harness):
    r1 = harness.post("같은 질문", client_id="dup-1")
    r2 = harness.post("같은 질문", client_id="dup-1")
    assert r1.status_code == 201 and r2.status_code == 201
    assert r1.json()["id"] == r2.json()["id"]
    assert len(harness.enqueuer.calls) == 1
    assert len(harness.store.jobs) == 1


def test_fr_web_007_bot_post_no_trigger(harness):
    """Bot 계정은 로그인 불가 + 토큰이 있어도 인증 거부 (loop guard)."""
    resp = harness.post("자기 답변에 반응?", user=harness.bot)
    assert resp.status_code == 401
    assert harness.enqueuer.calls == []


def test_trigger_word_stripped(harness):
    harness.store.bindings[harness.channel.id] = binding_for(
        harness.channel, mode=ChannelMode.TRIGGER_WORD, trigger_word="!rag"
    )
    assert harness.post("!rag  연차 규정").status_code == 201
    job = harness.store.jobs[0]
    import asyncio

    raw = asyncio.run(harness.redis.get(f"chat:req:{job['id']}"))
    assert ChatRequest.model_validate_json(raw).message == "연차 규정"


def test_trigger_miss_no_job(harness):
    harness.store.bindings[harness.channel.id] = binding_for(
        harness.channel, mode=ChannelMode.TRIGGER_WORD, trigger_word="!rag"
    )
    resp = harness.post("그냥 잡담")
    assert resp.status_code == 201
    assert harness.enqueuer.calls == [] and harness.store.jobs == []
    assert harness.sockets.names() == ["post.created"]  # 일반 메시지로만 게시


def test_trigger_word_thread_followup_without_trigger(harness):
    """Bot 이 이미 답한 thread 의 답글은 trigger 없이도 후속 질문으로 처리."""
    harness.store.bindings[harness.channel.id] = binding_for(
        harness.channel,
        mode=ChannelMode.TRIGGER_WORD,
        trigger_word="!rag",
        conversation_mode=ConversationMode.THREAD,
    )
    root = harness.post("!rag 첫 질문").json()
    bot_post = harness.store.posts[harness.store.jobs[0]["bot_post_id"]]
    assert bot_post.root_id == root["id"]  # THREAD 모드: 질문을 root 로 thread 답변
    harness.post("후속 질문", root_id=root["id"])
    assert len(harness.enqueuer.calls) == 2


def test_channel_not_bound_no_job(harness):
    del harness.store.bindings[harness.channel.id]
    resp = harness.post("질문")
    assert resp.status_code == 201
    assert harness.enqueuer.calls == []


def test_disabled_binding_no_job(harness):
    harness.store.bindings[harness.channel.id] = binding_for(harness.channel, enabled=False)
    assert harness.post("질문").status_code == 201
    assert harness.enqueuer.calls == []


def test_nested_reply_rejected(harness):
    root = harness.post("루트").json()
    reply = harness.post("답글", root_id=root["id"]).json()
    resp = harness.post("답글의 답글", root_id=reply["id"])
    assert resp.status_code == 400 and resp.json()["error"]["code"] == "NESTED_REPLY"


def test_rate_limit_429(harness):
    harness.settings.rate_limit_per_user_per_min = 2
    codes = [harness.post(f"q{i}").status_code for i in range(3)]
    assert codes == [201, 201, 429]
    assert len(harness.enqueuer.calls) == 2


def test_enqueue_failure_marks_bot_post_error(harness):
    harness.enqueuer.fail = True
    assert harness.post("질문").status_code == 201
    job = harness.store.jobs[0]
    assert job["status"] == "FAILED"
    bot_post = harness.store.posts[job["bot_post_id"]]
    assert bot_post.props["kind"] == "error" and bot_post.props["streaming"] is False
    assert "post.updated" in harness.sockets.names()


def test_thread_view_and_delete(harness):
    root = harness.post("루트 질문").json()
    harness.post("답글", root_id=root["id"])
    th = harness.client.get(f"/api/v1/posts/{root['id']}/thread", headers=harness.auth())
    assert th.status_code == 200
    # DEDICATED 채널: thread 답글도 질문 → 같은 thread 에 Bot placeholder 가 붙는다
    replies = th.json()["replies"]
    assert [r["type"] for r in replies] == ["user", "bot"]
    assert th.json()["root"]["reply_count"] == 2
    # bob(비멤버)은 thread 조회 불가
    assert (
        harness.client.get(
            f"/api/v1/posts/{root['id']}/thread", headers=harness.auth(harness.bob)
        ).status_code
        == 404
    )
    assert (
        harness.client.delete(f"/api/v1/posts/{root['id']}", headers=harness.auth()).status_code
        == 204
    )
    assert "post.deleted" in harness.sockets.names()


def test_sidebar_and_channel_detail_member_only(harness):
    sb = harness.client.get("/api/v1/channels/sidebar", headers=harness.auth()).json()
    assert [c["name"] for c in sb["all"]] == ["rag-cloud-ops"]
    detail = harness.client.get("/api/v1/channels/rag-cloud-ops", headers=harness.auth()).json()
    assert detail["me"]["permissions"]["use_bot"] is True
    assert detail["binding"]["mode"] == "DEDICATED_CHANNEL"
    assert "knowledge_scope" not in detail["binding"]
    assert harness.client.get("/api/v1/channels/rag-hr", headers=harness.auth()).status_code == 404


def test_posts_list_root_only_with_reply_count(harness):
    root = harness.post("루트").json()
    harness.post("답글", root_id=root["id"])
    items = harness.client.get(
        f"/api/v1/channels/{harness.channel.id}/posts", headers=harness.auth()
    ).json()["items"]
    # DEDICATED + CHANNEL 모드: 질문 2건 모두 트리거 → root 목록 = [루트, 루트의 Bot 답변]
    assert all(p["root_id"] is None for p in items)
    assert items[0]["id"] == root["id"] and items[0]["reply_count"] >= 1


def test_secret_never_in_logs(harness, caplog):
    caplog.set_level(logging.DEBUG)
    harness.client.post("/api/v1/auth/login", json=harness.login_body("alice@example.com"))
    harness.post("질문")
    joined = caplog.text
    for secret in ("test-jwt-secret", "test-pepper", "test-signing-key"):
        assert secret not in joined
    assert harness.token(harness.alice) not in joined


# ---------------------------------------------------------------- FR-CHAT-014 LLM 직접 대화
async def _stored_request(harness, idx: int = 0) -> ChatRequest:
    raw = await harness.redis.get(f"chat:req:{harness.store.jobs[idx]['id']}")
    return ChatRequest.model_validate_json(raw)


async def test_fr_chat_014_slash_prefix_is_direct_and_stripped(harness):
    harness.store.bindings[harness.channel.id] = binding_for(
        harness.channel, direct_llm_enabled=True
    )
    assert harness.post("/  파이썬 리스트 역순 정렬").status_code == 201
    req = await _stored_request(harness)
    assert req.direct is True and req.message == "파이썬 리스트 역순 정렬"
    bot_post = harness.store.posts[harness.store.jobs[0]["bot_post_id"]]
    assert bot_post.props["direct"] is True and bot_post.props["ack"] is False


async def test_fr_chat_014_disabled_channel_keeps_slash_as_rag_question(harness):
    harness.post("/etc/hosts 설정 위치")  # 기본 binding: direct_llm_enabled=False
    req = await _stored_request(harness)
    assert req.direct is False and req.message == "/etc/hosts 설정 위치"
    bot_post = harness.store.posts[harness.store.jobs[0]["bot_post_id"]]
    assert "direct" not in bot_post.props


async def test_fr_chat_014_trigger_word_channel_slash_triggers_without_trigger_word(harness):
    harness.store.bindings[harness.channel.id] = binding_for(
        harness.channel, mode=ChannelMode.TRIGGER_WORD, trigger_word="!rag", direct_llm_enabled=True
    )
    harness.post("/번역해줘 hello")
    harness.post("!rag /요약해줘")
    harness.post("그냥 잡담")  # 트리거 없음
    assert len(harness.store.jobs) == 2
    assert [(r.direct, r.message) for r in [await _stored_request(harness, i) for i in (0, 1)]] == [
        (True, "번역해줘 hello"),
        (True, "요약해줘"),
    ]


def test_fr_chat_014_slash_only_is_not_a_question(harness):
    harness.store.bindings[harness.channel.id] = binding_for(
        harness.channel, direct_llm_enabled=True
    )
    assert harness.post("/").status_code == 201
    assert harness.enqueuer.calls == []


def test_fr_chat_014_channel_detail_exposes_direct_flag(harness):
    harness.store.bindings[harness.channel.id] = binding_for(
        harness.channel, direct_llm_enabled=True
    )
    resp = harness.client.get(f"/api/v1/channels/{harness.channel.id}", headers=harness.auth())
    assert resp.status_code == 200, resp.text
    assert resp.json()["binding"]["direct_llm_enabled"] is True
