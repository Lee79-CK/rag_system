"""Feedback 계층 스키마 (v1.1 추가) — docs/TDD.md §4.5."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field

FEEDBACK_ACTION_UP = "feedback:up"
FEEDBACK_ACTION_DOWN = "feedback:down"


class FeedbackValue(StrEnum):
    UP = "UP"  # 👍 도움됨
    DOWN = "DOWN"  # 👎 아쉬움


class WidgetActionRequest(BaseModel):
    """Web Chat 버튼 액션 POST /api/v1/actions body (aiops WidgetActionRequest 호환).

    피드백 버튼은 `value` 에 Bot Post props 로 전달된 feedback_token 을 실어 보낸다.
    token = HMAC-SHA256(FEEDBACK_SIGNING_KEY, f"{message_id}:{post_id}") — 위·변조 방지.
    """

    post_id: str = Field(min_length=1, max_length=64)
    block_id: str = Field(min_length=1, max_length=64)
    action_id: str = Field(min_length=1, max_length=64)
    value: str | None = Field(default=None, max_length=256)


class MessageFeedback(BaseModel):
    message_id: str
    user_id: str
    value: FeedbackValue
    created_at: datetime
