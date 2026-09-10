"""답변 피드백(👍/👎) actions 테스트 (docs/TDD.md §7.1.4)."""

from __future__ import annotations

from conftest import make_action_body


def _seed_message(harness, message_id="msg-1", channel_id="chan1"):
    harness.feedback_repo.add_message(message_id, channel_id)


def test_fb_valid_signature_upserts(harness):
    _seed_message(harness)
    resp = harness.client.post(
        "/integrations/mattermost/v1/actions",
        json=make_action_body(harness, message_id="msg-1", value="UP"),
    )
    assert resp.status_code == 200
    assert resp.json()["ephemeral_text"].startswith("피드백이 반영")
    assert len(harness.feedback_repo.feedback) == 1
    assert harness.enqueuer.calls == []  # 피드백 경로는 Queue 미호출


def test_fb_invalid_signature_401(harness):
    _seed_message(harness)
    resp = harness.client.post(
        "/integrations/mattermost/v1/actions",
        json=make_action_body(harness, message_id="msg-1", value="UP", sig="forged-signature"),
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "INVALID_SIGNATURE"
    assert len(harness.feedback_repo.feedback) == 0  # DB 무변경


def test_fb_reclick_updates_value(harness):
    _seed_message(harness)
    up = make_action_body(harness, message_id="msg-1", value="UP")
    down = make_action_body(harness, message_id="msg-1", value="DOWN")

    r1 = harness.client.post("/integrations/mattermost/v1/actions", json=up)
    r2 = harness.client.post("/integrations/mattermost/v1/actions", json=down)

    assert r1.status_code == 200
    assert r2.status_code == 200
    assert len(harness.feedback_repo.feedback) == 1  # 행 수 유지
    row = harness.feedback_repo.feedback[("msg-1", "user1")]
    assert row["value"].value == "DOWN"


def test_fb_cross_channel_message_rejected(harness):
    _seed_message(harness, message_id="msg-1", channel_id="chan1")
    # 답변은 chan1 소속인데 chan2 에서 클릭 → 403
    resp = harness.client.post(
        "/integrations/mattermost/v1/actions",
        json=make_action_body(harness, message_id="msg-1", value="UP", channel_id="chan2"),
    )
    assert resp.status_code == 403
    assert len(harness.feedback_repo.feedback) == 0


def test_fb_target_not_found_404(harness):
    # message 미존재 → 404
    resp = harness.client.post(
        "/integrations/mattermost/v1/actions",
        json=make_action_body(harness, message_id="ghost", value="UP"),
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "FEEDBACK_TARGET_NOT_FOUND"


def test_fb_no_rag_call(harness):
    _seed_message(harness)
    harness.client.post(
        "/integrations/mattermost/v1/actions",
        json=make_action_body(harness, message_id="msg-1", value="UP"),
    )
    # 피드백 경로에서 Queue/LLM 미호출 (§7.1.4 MUST)
    assert harness.enqueuer.calls == []


def test_fb_missing_signing_key_rejects_all(harness):
    """서명 키 파일이 없으면 어떤 서명도(빈 키로 만든 서명 포함) 401 — fail-closed."""
    from mattermost_adapter import feedback_signature

    _seed_message(harness)
    harness.settings.feedback_signing_key_file = "/nonexistent/feedback-signing-key"
    assert harness.settings.feedback_signing_key() == b""
    forged_with_empty_key = feedback_signature(b"", "msg-1", "UP")
    resp = harness.client.post(
        "/integrations/mattermost/v1/actions",
        json=make_action_body(harness, message_id="msg-1", value="UP", sig=forged_with_empty_key),
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "INVALID_SIGNATURE"
    assert len(harness.feedback_repo.feedback) == 0
