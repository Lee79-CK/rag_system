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


# ---------------------------------------------------------------------------
# 코드 리뷰 후속 (docs/code-review-2026-09-10.md) — fail-closed / 롤백 / 기본 trigger
# ---------------------------------------------------------------------------


def test_fr_mm_002_missing_token_file_denies_empty_token(harness):
    """Secret 파일이 없으면 기대 토큰이 ''. 예전엔 compare_digest('', '')=True 로 인증이 통과했다."""
    from bridge.core.security import constant_time_token_check

    assert constant_time_token_check("", "") is False
    assert constant_time_token_check("anything", "") is False

    harness.settings.mattermost_outgoing_token_secret_file = "/nonexistent/outgoing-token"
    assert harness.settings.outgoing_token() == ""
    resp = harness.client.post(
        "/integrations/mattermost/v1/outgoing",
        json=make_outgoing_payload(token="", post_id="empty-token"),
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "INVALID_TOKEN"
    assert harness.enqueuer.calls == []


def test_fr_mm_006_enqueue_failure_rolls_back_dedup_and_rows(harness):
    """enqueue 실패 → dedup 키/event/job 모두 되돌려 Mattermost 재전송이 처리되어야 한다."""
    import asyncio

    harness.enqueuer.fail_times = 1
    payload = make_outgoing_payload(post_id="rollback-post")

    r1 = harness.client.post("/integrations/mattermost/v1/outgoing", json=payload)
    assert r1.status_code == 500
    assert harness.event_repo.jobs == []
    assert harness.event_repo.events == []
    assert (
        asyncio.get_event_loop().run_until_complete(harness.redis.exists("mm:event:rollback-post"))
        == 0
    )

    # 재전송(enqueue 정상) → 정상 접수, job 1건
    r2 = harness.client.post("/integrations/mattermost/v1/outgoing", json=payload)
    assert r2.status_code == 200
    assert len(harness.enqueuer.calls) == 1
    assert len(harness.event_repo.jobs) == 1


def test_fr_mm_010_default_trigger_word_stripped():
    """binding.trigger_word 가 NULL 이고 전역 기본값(!rag)으로 게이트를 통과한 경우에도 prefix 를 제거한다."""
    from rag_schemas import OutgoingWebhookPayload

    binding = ChannelBinding(
        id="b4",
        team_id="team1",
        channel_id="chan1",
        channel_name="general",
        mode=ChannelMode.TRIGGER_WORD,
        trigger_word=None,
        enabled=True,
        knowledge_scope=KnowledgeScope(),
        incoming_webhook_secret_ref="mm-chan1",
    )
    payload = OutgoingWebhookPayload.model_validate(make_outgoing_payload(text="!rag 휴가 정책"))
    chat_request = to_chat_request(payload, binding, "trace-y", default_trigger="!rag")
    assert chat_request.message == "휴가 정책"


def test_enqueue_sets_job_timeout(monkeypatch):
    """RQ 기본 180s 는 파이프라인 최악치보다 짧다 — 명시적 job_timeout 을 전달해야 한다."""
    import rq
    from bridge.services import job_enqueuer

    captured: dict = {}

    class FakeJob:
        id = "rq-1"

    class FakeQueue:
        def __init__(self, name, connection=None):
            captured["queue"] = name

        def enqueue(self, target, *args, **kwargs):
            captured["target"] = target
            captured["args"] = args
            captured["kwargs"] = kwargs
            return FakeJob()

    monkeypatch.setattr(rq, "Queue", FakeQueue)
    assert job_enqueuer.enqueue_chat_job(None, "job-1") == "rq-1"
    assert captured["queue"] == "rag-chat"
    assert captured["args"] == ("job-1",)
    assert captured["kwargs"]["job_timeout"] == job_enqueuer.JOB_TIMEOUT_SECONDS >= 300
