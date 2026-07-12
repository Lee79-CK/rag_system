"""Mattermost 계층 스키마 — docs/TDD.md §4.1."""

from __future__ import annotations

from pydantic import BaseModel, Field, SecretStr


class OutgoingWebhookPayload(BaseModel):
    """Mattermost가 전송하는 원본 payload.

    JSON과 form-urlencoded 모두 이 모델로 정규화한다.
    """

    token: SecretStr
    team_id: str
    team_domain: str | None = None
    channel_id: str
    channel_name: str
    timestamp: int | None = None
    user_id: str
    user_name: str
    post_id: str
    root_id: str = ""  # 빈 문자열 = Thread 아님
    text: str
    trigger_word: str | None = None


class IncomingWebhookMessage(BaseModel):
    """Bridge → Mattermost 게시 본문."""

    channel: str  # channel_name (PRD §17.3)
    username: str = "RAG Assistant"
    text: str  # Mattermost Markdown
    attachments: list[dict] = Field(default_factory=list)  # v1.1: Interactive Attachments
