"""libs/schemas unit tests (M1 DoD: 스키마 unit test green)."""

from __future__ import annotations

import pytest
from pydantic import TypeAdapter, ValidationError
from rag_schemas import (
    ChannelBinding,
    ChannelMode,
    ChatRequest,
    ConversationMode,
    ErrorDetail,
    ErrorResponse,
    KnowledgeScope,
    QdrantChunkPayload,
    WidgetActionRequest,
    scope_key,
)
from rag_schemas.webchat import (
    Block,
    LoginRequest,
    PostDto,
    TableBlock,
    channel_room,
)


def _binding(mode: ConversationMode = ConversationMode.CHANNEL) -> ChannelBinding:
    return ChannelBinding(
        id="b1",
        channel_id="channel-001",
        channel_name="rag-cloud-ops",
        mode=ChannelMode.DEDICATED_CHANNEL,
        enabled=True,
        conversation_mode=mode,
    )


def _request(**over) -> ChatRequest:
    base = {
        "source": "web",
        "channel_id": "c",
        "user_id": "u",
        "user_name": "un",
        "post_id": "p",
        "root_id": None,
        "bot_post_id": "bp",
        "message": "질문",
        "trace_id": "trace-1",
    }
    base.update(over)
    return ChatRequest(**base)


def test_scope_key_channel_mode():
    assert scope_key(_binding(ConversationMode.CHANNEL), None, "post-9") == "channel-001"


def test_scope_key_thread_mode_uses_root_then_post():
    b = _binding(ConversationMode.THREAD)
    assert scope_key(b, "root-7", "post-9") == "channel-001:root-7"
    # thread 시작 메시지는 자기 post_id가 root
    assert scope_key(b, None, "post-9") == "channel-001:post-9"


def test_scope_key_stateless_mode_uses_post():
    assert scope_key(_binding(ConversationMode.STATELESS), None, "post-9") == "channel-001:post-9"


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


def test_widget_action_request_limits():
    req = WidgetActionRequest(post_id="p1", block_id="fb", action_id="feedback:up", value="t")
    assert req.value == "t"
    with pytest.raises(ValidationError):
        WidgetActionRequest(post_id="", block_id="fb", action_id="feedback:up")


def test_error_response_shape():
    err = ErrorResponse(
        error=ErrorDetail(code="INVALID_TOKEN", message="토큰 불일치", request_id="r1")
    )
    assert err.error.code == "INVALID_TOKEN"
    assert err.error.detail is None


def test_chat_request_source_literal():
    assert _request().source == "web"
    with pytest.raises(ValidationError):
        _request(source="mattermost")


def test_block_union_discriminates_by_type():
    ta = TypeAdapter(list[Block])
    blocks = ta.validate_python(
        [
            {"type": "divider"},
            {"type": "context", "text": "출처"},
            {"type": "table", "columns": [{"key": "n", "label": "#"}], "rows": [{"n": "1"}]},
        ]
    )
    assert isinstance(blocks[2], TableBlock)
    with pytest.raises(ValidationError):
        ta.validate_python([{"type": "approval_card"}])


def test_post_dto_defaults_match_web_contract():
    p = PostDto(id="p", channel_id="c", type="bot", created_at="2026-01-01T00:00:00Z")
    dumped = p.model_dump()
    # chat-web PostItem 은 reactions/participants 를 배열로 가정한다.
    assert dumped["reactions"] == [] and dumped["participants"] == []
    assert dumped["props"] == {} and dumped["reply_count"] == 0


def test_login_request_requires_prehash_not_password():
    with pytest.raises(ValidationError):
        LoginRequest(email="a@b.c", prehash="short", client_nonce="n" * 8, timestamp=1)


def test_channel_room_name():
    assert channel_room("abc") == "channel:abc"
