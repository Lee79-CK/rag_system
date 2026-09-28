"""chat_posts row → PostDto 매핑. gateway(조회/생성) 와 worker(답변 갱신) 가 같은 모양을 쓴다."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from rag_schemas.webchat import PostDto, UserBrief

# props 중 클라이언트에 내보내지 않는 내부 키 (message_id 는 피드백 검증용으로 서버만 사용).
_INTERNAL_PROPS = frozenset({"message_id", "chat_job_id"})


@dataclass(slots=True)
class PostRow:
    id: str
    channel_id: str
    root_id: str | None
    type: str
    message: str
    created_at: datetime | str
    blocks: list[dict[str, Any]] | None = None
    props: dict[str, Any] = field(default_factory=dict)
    edit_at: datetime | str | None = None
    delete_at: datetime | str | None = None
    user: UserBrief | None = None
    reply_count: int = 0
    last_reply_at: datetime | str | None = None
    participants: list[UserBrief] = field(default_factory=list)


def _iso(v: datetime | str | None) -> str | None:
    if v is None:
        return None
    return v.isoformat() if isinstance(v, datetime) else v


def to_post_dto(row: PostRow) -> PostDto:
    props = {k: v for k, v in (row.props or {}).items() if k not in _INTERNAL_PROPS}
    return PostDto.model_validate(
        {
            "id": row.id,
            "channel_id": row.channel_id,
            "root_id": row.root_id,
            "type": row.type,
            "user": row.user,
            "message": row.message or "",
            "blocks": row.blocks or None,
            "props": props,
            "created_at": _iso(row.created_at),
            "edit_at": _iso(row.edit_at),
            "delete_at": _iso(row.delete_at),
            "reply_count": row.reply_count,
            "last_reply_at": _iso(row.last_reply_at),
            "participants": row.participants,
        }
    )
