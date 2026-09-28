"""Binding / Scope 계층 스키마 — docs/TDD.md §4.3."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from rag_schemas.chat import ConversationMode


class ChannelMode(StrEnum):
    DEDICATED_CHANNEL = "DEDICATED_CHANNEL"  # 모든 top-level 메시지/답글에 응답
    TRIGGER_WORD = "TRIGGER_WORD"  # trigger_word 로 시작하는 메시지에만 응답


class KnowledgeScope(BaseModel):
    categories: list[str] = Field(default_factory=list)
    departments: list[str] = Field(default_factory=list)
    security_levels: list[str] = Field(default_factory=lambda: ["INTERNAL"])
    document_ids: list[str] = Field(default_factory=list)  # 명시 지정 시


class ChannelBinding(BaseModel):
    id: str
    channel_id: str  # chat_channels.id — Qdrant allowed_channel_ids 와 동일 값
    channel_name: str
    mode: ChannelMode
    trigger_word: str | None = None
    enabled: bool
    conversation_mode: ConversationMode = ConversationMode.CHANNEL
    history_turns: int = 8
    knowledge_scope: KnowledgeScope = Field(default_factory=KnowledgeScope)
    mention_user: bool = True
    ack_message_enabled: bool = True
    feedback_enabled: bool = True  # v1.1 — Channel별 피드백 on/off


def scope_key(binding: ChannelBinding, root_id: str | None, post_id: str) -> str:
    """PRD §18.3 Conversation Scope Key."""
    match binding.conversation_mode:
        case ConversationMode.CHANNEL:
            return binding.channel_id
        case ConversationMode.THREAD:
            rid = root_id or post_id  # thread 시작 메시지는 자기 post_id가 root
            return f"{binding.channel_id}:{rid}"
        case ConversationMode.STATELESS:
            return f"{binding.channel_id}:{post_id}"
        case _:
            raise ValueError(f"unknown conversation_mode: {binding.conversation_mode}")
