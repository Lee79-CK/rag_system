"""Feedback 계층 스키마 (v1.1 추가) — docs/TDD.md §4.5."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel


class FeedbackValue(StrEnum):
    UP = "UP"  # 👍 도움됨
    DOWN = "DOWN"  # 👎 아쉬움


class InteractiveActionContext(BaseModel):
    """답변 Post의 버튼에 심는 context. Bridge가 서명하여 위·변조 방지."""

    action: Literal["feedback"]
    message_id: str  # messages.id (assistant 답변)
    chat_job_id: str
    value: FeedbackValue
    sig: str  # HMAC-SHA256(FEEDBACK_SIGNING_KEY, f"{message_id}:{value}")


class InteractiveActionRequest(BaseModel):
    """Mattermost Interactive Message Action POST body (필요 필드만)."""

    user_id: str
    user_name: str | None = None
    post_id: str  # 버튼이 달린 답변 Post의 id
    channel_id: str
    team_id: str | None = None
    context: InteractiveActionContext


class MessageFeedback(BaseModel):
    message_id: str
    user_id: str
    value: FeedbackValue
    created_at: datetime
