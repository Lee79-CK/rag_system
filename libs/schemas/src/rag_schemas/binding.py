"""Binding / Scope 계층 스키마 — docs/TDD.md §4.3."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from rag_schemas.chat import ConversationMode


class ChannelMode(StrEnum):
    DEDICATED_CHANNEL = "DEDICATED_CHANNEL"
    TRIGGER_WORD = "TRIGGER_WORD"


class KnowledgeScope(BaseModel):
    categories: list[str] = Field(default_factory=list)
    departments: list[str] = Field(default_factory=list)
    security_levels: list[str] = Field(default_factory=lambda: ["INTERNAL"])
    document_ids: list[str] = Field(default_factory=list)  # 명시 지정 시


class ChannelBinding(BaseModel):
    id: str
    team_id: str
    channel_id: str
    channel_name: str
    mode: ChannelMode
    trigger_word: str | None = None
    enabled: bool
    conversation_mode: ConversationMode = ConversationMode.CHANNEL
    history_turns: int = 8
    knowledge_scope: KnowledgeScope = Field(default_factory=KnowledgeScope)
    incoming_webhook_secret_ref: str  # K8s Secret 이름. URL 자체 아님
    mention_user: bool = True
    ack_message_enabled: bool = True
    feedback_enabled: bool = True  # v1.1 — Channel별 피드백 on/off


def scope_key(binding: ChannelBinding, root_id: str | None, post_id: str) -> str:
    """PRD §18.3 Conversation Scope Key."""
    match binding.conversation_mode:
        case ConversationMode.CHANNEL:
            return f"{binding.team_id}:{binding.channel_id}"
        case ConversationMode.THREAD:
            rid = root_id or post_id  # thread 시작 메시지는 자기 post_id가 root
            return f"{binding.team_id}:{binding.channel_id}:{rid}"
        case ConversationMode.STATELESS:
            return f"{binding.team_id}:{binding.channel_id}:{post_id}"
