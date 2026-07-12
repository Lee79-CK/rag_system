"""Chat 계층 스키마 — docs/TDD.md §4.2."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class ConversationMode(StrEnum):
    CHANNEL = "CHANNEL"
    THREAD = "THREAD"
    STATELESS = "STATELESS"


class ChatRequest(BaseModel):
    """내부 표준 요청. Mattermost 종속성 제거 완료 상태 (NFR-MAINT-006)."""

    source: Literal["mattermost", "admin_console"]
    team_id: str
    channel_id: str
    channel_name: str
    user_id: str
    user_name: str
    post_id: str
    root_id: str | None = None
    message: str  # Trigger word 제거 완료된 순수 질문
    trace_id: str


class ChatJobStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    DELIVERY_PENDING = "DELIVERY_PENDING"
    DELIVERY_FAILED = "DELIVERY_FAILED"  # Dead Letter
    FAILED = "FAILED"


class Citation(BaseModel):
    document_id: str
    document_name: str
    page: int | None = None
    section: str | None = None
    excerpt: str  # 근거 요약 (최대 200자)
    score: float
    chunk_id: str


class RagCompletion(BaseModel):
    message_id: str
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    insufficient_evidence: bool = False
    usage: dict = Field(default_factory=dict)  # prompt_tokens, completion_tokens, stage latencies
