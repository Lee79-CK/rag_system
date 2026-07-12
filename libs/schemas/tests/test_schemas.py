"""libs/schemas unit tests (M1 DoD: 스키마 unit test green)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from rag_schemas import (
    ChannelBinding,
    ChannelMode,
    ChatRequest,
    ConversationMode,
    ErrorDetail,
    ErrorResponse,
    FeedbackValue,
    IncomingWebhookMessage,
    InteractiveActionContext,
    KnowledgeScope,
    OutgoingWebhookPayload,
    QdrantChunkPayload,
    scope_key,
)


def _binding(mode: ConversationMode = ConversationMode.CHANNEL) -> ChannelBinding:
    return ChannelBinding(
        id="b1",
        team_id="team-001",
        channel_id="channel-001",
        channel_name="rag-cloud-ops",
        mode=ChannelMode.DEDICATED_CHANNEL,
        enabled=True,
        conversation_mode=mode,
        incoming_webhook_secret_ref="mattermost-incoming-rag-cloud-ops",
    )


def test_outgoing_token_is_secret_and_hidden_in_repr():
    p = OutgoingWebhookPayload(
        token="super-secret-token",
        team_id="team-001",
        channel_id="channel-001",
        channel_name="rag-cloud-ops",
        user_id="u1",
        user_name="hong",
        post_id="post-1",
        text="hello",
    )
    # SecretStr must never leak the value via repr/str (NFR-SEC-006, §3.2).
    assert "super-secret-token" not in repr(p)
    assert "super-secret-token" not in str(p)
    assert p.token.get_secret_value() == "super-secret-token"


def test_root_id_defaults_to_empty_string():
    p = OutgoingWebhookPayload(
        token="t",
        team_id="team",
        channel_id="c",
        channel_name="n",
        user_id="u",
        user_name="un",
        post_id="p",
        text="q",
    )
    assert p.root_id == ""


def test_scope_key_channel_mode():
    assert scope_key(_binding(ConversationMode.CHANNEL), None, "post-9") == "team-001:channel-001"


def test_scope_key_thread_mode_uses_root_then_post():
    b = _binding(ConversationMode.THREAD)
    assert scope_key(b, "root-7", "post-9") == "team-001:channel-001:root-7"
    # thread 시작 메시지는 자기 post_id가 root
    assert scope_key(b, None, "post-9") == "team-001:channel-001:post-9"


def test_scope_key_stateless_mode_uses_post():
    assert scope_key(_binding(ConversationMode.STATELESS), None, "post-9") == (
        "team-001:channel-001:post-9"
    )


def test_knowledge_scope_defaults():
    ks = KnowledgeScope()
    assert ks.security_levels == ["INTERNAL"]
    assert ks.categories == [] and ks.departments == [] and ks.document_ids == []


def test_binding_default_flags():
    b = _binding()
    assert b.history_turns == 8
    assert b.mention_user is True
    assert b.ack_message_enabled is True
    assert b.feedback_enabled is True


def test_incoming_message_defaults():
    m = IncomingWebhookMessage(channel="rag-cloud-ops", text="답변")
    assert m.username == "RAG Assistant"
    assert m.attachments == []


def test_qdrant_payload_roundtrip():
    payload = QdrantChunkPayload(
        document_id="d1",
        document_version_id="v1",
        chunk_id="v1-00007",
        title="장애대응매뉴얼",
        source_file="/data/x.pdf",
        chunk_index=7,
        content_hash="sha256:abc",
        text="본문",
    )
    dumped = payload.model_dump()
    assert dumped["is_active"] is True
    assert dumped["language"] == "ko"
    assert QdrantChunkPayload(**dumped) == payload


def test_feedback_context_literal_action():
    ctx = InteractiveActionContext(
        action="feedback",
        message_id="m1",
        chat_job_id="j1",
        value=FeedbackValue.UP,
        sig="deadbeef",
    )
    assert ctx.value is FeedbackValue.UP
    with pytest.raises(ValidationError):
        InteractiveActionContext(
            action="not-feedback",  # type: ignore[arg-type]
            message_id="m1",
            chat_job_id="j1",
            value=FeedbackValue.UP,
            sig="x",
        )


def test_error_response_shape():
    err = ErrorResponse(
        error=ErrorDetail(code="INVALID_TOKEN", message="토큰 불일치", request_id="r1")
    )
    assert err.error.code == "INVALID_TOKEN"
    assert err.error.detail is None


def test_chat_request_source_literal():
    req = ChatRequest(
        source="mattermost",
        team_id="t",
        channel_id="c",
        channel_name="n",
        user_id="u",
        user_name="un",
        post_id="p",
        root_id=None,
        message="질문",
        trace_id="trace-1",
    )
    assert req.source == "mattermost"
    with pytest.raises(ValidationError):
        ChatRequest(
            source="slack",  # type: ignore[arg-type]
            team_id="t",
            channel_id="c",
            channel_name="n",
            user_id="u",
            user_name="un",
            post_id="p",
            root_id=None,
            message="q",
            trace_id="tr",
        )
