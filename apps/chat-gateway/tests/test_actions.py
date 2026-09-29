"""피드백 Action 테스트 (docs/TDD.md §7.1.4, v1.1)."""

from __future__ import annotations

from rag_schemas import FeedbackValue


def _fb(harness, post_id: str, token: str, action: str = "feedback:up", user=None):
    return harness.client.post(
        "/api/v1/actions",
        json={"post_id": post_id, "block_id": "fb", "action_id": action, "value": token},
        headers=harness.auth(user),
    )


def test_fb_valid_token_upserts(harness):
    post_id, message_id, token = harness.answered_bot_post()
    resp = _fb(harness, post_id, token)
    assert resp.status_code == 200, resp.text
    assert resp.json()["feedback"] == {"1": 1, "-1": 0}
    row = harness.store.feedback[(message_id, harness.alice.id)]
    assert row["value"] is FeedbackValue.UP
    assert harness.store.posts[post_id].props["feedback"] == {"1": 1, "-1": 0}
    assert "post.updated" in harness.sockets.names()


def test_fb_invalid_token_401(harness):
    post_id, _, _ = harness.answered_bot_post()
    resp = _fb(harness, post_id, "0" * 64)
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "INVALID_SIGNATURE"
    assert harness.store.feedback == {}


def test_fb_reclick_updates_value(harness):
    post_id, message_id, token = harness.answered_bot_post()
    _fb(harness, post_id, token, "feedback:up")
    resp = _fb(harness, post_id, token, "feedback:down")
    assert resp.json()["feedback"] == {"1": 0, "-1": 1}
    assert len(harness.store.feedback) == 1
    assert harness.store.feedback[(message_id, harness.alice.id)]["value"] is FeedbackValue.DOWN


def test_fb_non_member_404(harness):
    post_id, _, token = harness.answered_bot_post()
    resp = _fb(harness, post_id, token, user=harness.bob)  # bob 은 채널 비멤버
    assert resp.status_code == 404
    assert harness.store.feedback == {}


def test_fb_cross_channel_message_rejected(harness):
    """토큰이 유효해도 답변 message 의 채널과 Post 채널이 다르면 거부."""
    from gateway.repos import AnswerRef

    post_id, message_id, token = harness.answered_bot_post()
    harness.store.answers[post_id] = AnswerRef(message_id=message_id, channel_id=harness.other.id)
    resp = _fb(harness, post_id, token)
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "FEEDBACK_CHANNEL_MISMATCH"


def test_fb_target_not_found_404(harness):
    resp = _fb(harness, "00000000-0000-0000-0000-000000000000", "x")
    assert resp.status_code == 404
    user_post = harness.post("사용자 글").json()  # bot 이 아닌 Post
    assert _fb(harness, user_post["id"], "x").status_code == 404


def test_fb_unsupported_action_400(harness):
    post_id, _, token = harness.answered_bot_post()
    assert _fb(harness, post_id, token, "approve").status_code == 400


def test_fb_no_rag_call(harness):
    post_id, _, token = harness.answered_bot_post()
    _fb(harness, post_id, token)
    assert harness.enqueuer.calls == []  # 피드백 경로는 Queue/LLM 호출 금지


def test_fb_disabled_404(harness):
    harness.settings.feedback_enabled = False
    post_id, _, token = harness.answered_bot_post()
    assert _fb(harness, post_id, token).status_code == 404


def test_fb_missing_signing_key_rejects_all(harness):
    """서명키 파일이 없거나 비면 빈 키로 만든 토큰도 거부 (fail-closed, 리뷰 B-2 이식)."""
    from chat_adapter import feedback_token

    post_id, message_id, _ = harness.answered_bot_post()
    harness.settings.feedback_signing_key_file = "/nonexistent/fb"
    assert harness.settings.feedback_signing_key() == b""
    resp = _fb(harness, post_id, feedback_token(b"", message_id, post_id))
    assert resp.status_code == 401 and resp.json()["error"]["code"] == "INVALID_SIGNATURE"
    assert harness.store.feedback == {}
