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
    """내부 표준 요청. UI(Web Chat) 종속성 제거 완료 상태 (NFR-MAINT-006)."""

    source: Literal["web", "admin_console"]
    channel_id: str  # chat_channels.id
    user_id: str  # chat_users.id
    user_name: str  # display_name
    post_id: str  # 질문 Post (chat_posts.id)
    root_id: str | None = None  # thread root post id (top-level이면 None)
    bot_post_id: str  # 스트리밍 대상 Bot Post (placeholder, chat_posts.id)
    message: str  # Trigger word 제거 완료된 순수 질문
    trace_id: str
    direct: bool = False  # `/` 접두어 — RAG(검색) 없이 LLM 직접 대화 (FR-CHAT-014)


class ChatJobStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    DELIVERY_FAILED = "DELIVERY_FAILED"  # 답변 생성 완료, Post 갱신/Emit 실패
    FAILED = "FAILED"


class Citation(BaseModel):
    document_id: str
    document_name: str
    page: int | None = None
    section: str | None = None
    excerpt: str  # 근거 요약 (최대 200자)
    score: float
    chunk_id: str
    # 답변 본문의 근거 번호([n]) — 프롬프트의 [근거 문서] 번호와 같다. 인용된 문서만 남기므로 1..N 이 비연속일 수 있다.
    ref: int | None = None


class RagCompletion(BaseModel):
    message_id: str
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    insufficient_evidence: bool = False
    direct: bool = False  # LLM 직접 대화 답변 (근거 문서 없음, FR-CHAT-014)
    # 동기 completions(평가용) 전용: 컨텍스트로 선택된 검색 청크 전체(rerank 순). citations 는 본문이 인용한 것만이라
    # Recall@10 계산에는 이 값을 쓴다. Worker(Web Chat) 경로는 채우지 않는다.
    retrieved: list[Citation] = Field(default_factory=list)
    usage: dict = Field(default_factory=dict)  # prompt_tokens, completion_tokens, stage latencies
