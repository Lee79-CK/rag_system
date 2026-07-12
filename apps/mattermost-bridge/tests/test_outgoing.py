"""Outgoing 수신 파이프라인 테스트 (docs/TDD.md §7.1.3)."""

from __future__ import annotations

from urllib.parse import urlencode

from bridge.services.event_normalizer import to_chat_request
from conftest import make_outgoing_payload
from rag_schemas import ChannelBinding, ChannelMode, KnowledgeScope


def test_fr_mm_002_invalid_token_401(harness):
    resp = harness.client.post(
        "/integrations/mattermost/v1/outgoing",
        json=make_outgoing_payload(token="wrong-token"),
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "INVALID_TOKEN"
    assert harness.enqueuer.calls == []


def test_fr_mm_006_duplicate_post_id_single_job(harness):
    payload = make_outgoing_payload(post_id="dup-post")
    r1 = harness.client.post("/integrations/mattermost/v1/outgoing", json=payload)
    r2 = harness.client.post("/integrations/mattermost/v1/outgoing", json=payload)

    assert r1.status_code == 200
    assert r2.status_code == 200  # 중복은 조용히 200 (§3.3 note)
    assert len(harness.enqueuer.calls) == 1
    assert len(harness.event_repo.jobs) == 1


def test_fr_mm_007_bot_message_ignored(harness):
    resp = harness.client.post(
        "/integrations/mattermost/v1/outgoing",
        json=make_outgoing_payload(user_name="RAG Assistant"),
    )
    assert resp.status_code == 200
    assert harness.enqueuer.calls == []
    assert harness.event_repo.jobs == []


def test_form_urlencoded_payload_parsed(harness):
    body = urlencode(make_outgoing_payload(post_id="form-post"))
    resp = harness.client.post(
        "/integrations/mattermost/v1/outgoing",
        content=body,
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 200
    assert len(harness.enqueuer.calls) == 1


def test_trigger_word_stripped():
    binding = ChannelBinding(
        id="b2",
        team_id="team1",
        channel_id="chan1",
        channel_name="general",
        mode=ChannelMode.TRIGGER_WORD,
        trigger_word="!rag",
        enabled=True,
        knowledge_scope=KnowledgeScope(),
        incoming_webhook_secret_ref="mm-chan1",
    )
    from rag_schemas import OutgoingWebhookPayload

    payload = OutgoingWebhookPayload.model_validate(make_outgoing_payload(text="!rag 질문"))
    chat_request = to_chat_request(payload, binding, "trace-x")
    assert chat_request.message == "질문"


def test_trigger_miss_ignored(harness):
    # TRIGGER_WORD 모드 binding으로 교체 후 trigger 미포함 메시지 → 무시
    harness.binding_repo.add(
        ChannelBinding(
            id="b3",
            team_id="team1",
            channel_id="chan1",
            channel_name="general",
            mode=ChannelMode.TRIGGER_WORD,
            trigger_word="!rag",
            enabled=True,
            knowledge_scope=KnowledgeScope(),
            incoming_webhook_secret_ref="mm-chan1",
        )
    )
    resp = harness.client.post(
        "/integrations/mattermost/v1/outgoing",
        json=make_outgoing_payload(text="트리거 없는 질문", post_id="nt-1"),
    )
    assert resp.status_code == 200
    assert harness.enqueuer.calls == []


def test_channel_not_bound_403(harness):
    resp = harness.client.post(
        "/integrations/mattermost/v1/outgoing",
        json=make_outgoing_payload(channel_id="unknown-chan"),
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "CHANNEL_NOT_BOUND"


def test_secret_never_in_logs(harness, capsys):
    harness.client.post(
        "/integrations/mattermost/v1/outgoing",
        json=make_outgoing_payload(post_id="log-post"),
    )
    out = capsys.readouterr()
    combined = out.out + out.err
    assert harness.settings.outgoing_token() == "test-outgoing-token"
    assert "test-outgoing-token" not in combined
    assert "incoming_webhook_secret_ref" not in combined or "mm-chan1" not in combined
