"""피드백 조회 API (read-only, v1.1) — docs/TDD.md §7.5.

접근 역할: SYS_ADMIN, QUALITY_EVALUATOR.
- GET /api/v1/feedback/summary        전체 👍/👎 집계 + 만족률(UP/(UP+DOWN))
- GET /api/v1/feedback/by-channel     Channel별 집계
- GET /api/v1/feedback/messages?value=DOWN   답변 목록 (messages + citations join)
- GET /api/v1/messages/{id}/feedback  특정 답변 피드백 상세
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, status
from rag_schemas import FeedbackValue
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from admin.api.evaluation import question_for
from admin.api.responses import api_error, envelope
from admin.core.rbac import QUALITY_EVALUATOR, SYS_ADMIN, Principal, require_roles
from admin.db.models import Citation, EvaluationCandidate, Message, MessageFeedbackRow
from admin.db.session import get_db

router = APIRouter(prefix="/api/v1", tags=["feedback"])

_ROLES = (SYS_ADMIN, QUALITY_EVALUATOR)


def _ratio(up: int, down: int) -> float | None:
    total = up + down
    return round(up / total, 4) if total else None


@router.get("/feedback/summary")
def feedback_summary(
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles(*_ROLES)),
) -> dict:
    rows = db.execute(
        select(MessageFeedbackRow.value, func.count()).group_by(MessageFeedbackRow.value)
    ).all()
    counts = dict(rows)
    up = int(counts.get(FeedbackValue.UP, 0))
    down = int(counts.get(FeedbackValue.DOWN, 0))
    return envelope(
        {
            "up": up,
            "down": down,
            "total": up + down,
            "satisfaction_ratio": _ratio(up, down),
        }
    )


@router.get("/feedback/by-channel")
def feedback_by_channel(
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles(*_ROLES)),
) -> dict:
    rows = db.execute(
        select(
            MessageFeedbackRow.channel_id,
            MessageFeedbackRow.value,
            func.count(),
        ).group_by(MessageFeedbackRow.channel_id, MessageFeedbackRow.value)
    ).all()

    by_channel: dict[str, dict] = {}
    for channel_id, value, count in rows:
        entry = by_channel.setdefault(channel_id, {"channel_id": channel_id, "up": 0, "down": 0})
        if value == FeedbackValue.UP:
            entry["up"] = int(count)
        elif value == FeedbackValue.DOWN:
            entry["down"] = int(count)

    result = []
    for entry in by_channel.values():
        entry["total"] = entry["up"] + entry["down"]
        entry["satisfaction_ratio"] = _ratio(entry["up"], entry["down"])
        result.append(entry)
    return envelope(result, count=len(result))


@router.get("/feedback/messages")
def feedback_messages(
    value: FeedbackValue = Query(default=FeedbackValue.DOWN),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles(*_ROLES)),
) -> dict:
    """지정 피드백(기본 👎) 답변 목록 — 질문/답변/Citation join, 품질 개선 분석용."""
    fb_rows = db.execute(
        select(MessageFeedbackRow, Message)
        .join(Message, Message.id == MessageFeedbackRow.message_id)
        .where(MessageFeedbackRow.value == value.value)
        .order_by(MessageFeedbackRow.created_at.desc())
    ).all()

    promoted: dict[uuid.UUID | None, str] = dict(
        db.execute(
            select(EvaluationCandidate.message_id, EvaluationCandidate.status).where(
                EvaluationCandidate.message_id.in_({msg.id for _fb, msg in fb_rows})
            )
        )
        .tuples()
        .all()
    )
    items = []
    for fb, msg in fb_rows:
        citations = (
            db.execute(
                select(Citation).where(Citation.message_id == msg.id).order_by(Citation.rank)
            )
            .scalars()
            .all()
        )
        items.append(
            {
                "message_id": str(msg.id),
                "conversation_id": str(msg.conversation_id),
                "question": question_for(db, msg),
                "content": msg.content,
                "channel_id": fb.channel_id,
                # 평가셋 후보로 승격됐으면 그 상태(PENDING/ACCEPTED/REJECTED), 아니면 null
                "candidate_status": promoted.get(msg.id),
                "value": fb.value,
                "created_at": fb.created_at.isoformat() if fb.created_at else None,
                "citations": [
                    {
                        "chunk_id": c.chunk_id,
                        "document_id": str(c.document_id) if c.document_id else None,
                        "score": c.score,
                        "rank": c.rank,
                    }
                    for c in citations
                ],
            }
        )
    return envelope(items, count=len(items))


@router.get("/messages/{message_id}/feedback")
def message_feedback(
    message_id: uuid.UUID,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles(*_ROLES)),
) -> dict:
    msg = db.get(Message, message_id)
    if msg is None:
        raise api_error("NOT_FOUND", "메시지를 찾을 수 없습니다.", status.HTTP_404_NOT_FOUND)

    rows = (
        db.execute(
            select(MessageFeedbackRow)
            .where(MessageFeedbackRow.message_id == message_id)
            .order_by(MessageFeedbackRow.created_at.desc())
        )
        .scalars()
        .all()
    )
    up = sum(1 for r in rows if r.value == FeedbackValue.UP)
    down = sum(1 for r in rows if r.value == FeedbackValue.DOWN)
    return envelope(
        {
            "message_id": str(message_id),
            "up": up,
            "down": down,
            "satisfaction_ratio": _ratio(up, down),
            "entries": [
                {
                    "user_id": r.user_id,
                    "value": r.value,
                    "channel_id": r.channel_id,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                    "updated_at": r.updated_at.isoformat() if r.updated_at else None,
                }
                for r in rows
            ],
        }
    )
