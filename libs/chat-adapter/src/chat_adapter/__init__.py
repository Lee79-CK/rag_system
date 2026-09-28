"""chat_adapter — Web Chat(chat-web) 표현 계층 Adapter (§13.2).

RAG Domain Logic은 포함하지 않는다. chat-gateway 와 rag-worker 가 공유한다
(apps/* 간 직접 import 금지 규칙 — 공유 코드는 libs/* 로만).
"""

from chat_adapter.emitter import DeltaStream, SocketManager, StreamEmitter, redis_emitter
from chat_adapter.mapper import PostRow, to_post_dto
from chat_adapter.render import (
    ERROR_TEXT,
    feedback_token,
    render_answer,
    verify_feedback_token,
)

__all__ = [
    "DeltaStream",
    "ERROR_TEXT",
    "PostRow",
    "SocketManager",
    "StreamEmitter",
    "feedback_token",
    "redis_emitter",
    "render_answer",
    "to_post_dto",
    "verify_feedback_token",
]
