"""Chat Job 조회 API — docs/TDD.md §7.5.

Web Chat 에서는 답변이 chat_posts(Bot Post) 로 직접 반영되므로 별도 delivery 재시도가 없다.
DELIVERY_FAILED(= Bot Post 갱신/emit 실패) 는 사용자가 채널을 다시 열면 DB 기준으로 수렴한다.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from admin.api.responses import envelope
from admin.core.rbac import SYS_ADMIN, Principal, require_roles
from admin.db.models import ChatJob
from admin.db.session import get_db

router = APIRouter(prefix="/api/v1/chat-jobs", tags=["chat-jobs"])


def _job_view(j: ChatJob) -> dict:
    return {
        "id": str(j.id),
        "post_id": str(j.post_id) if j.post_id else None,
        "bot_post_id": str(j.bot_post_id) if j.bot_post_id else None,
        "conversation_id": str(j.conversation_id) if j.conversation_id else None,
        "status": j.status,
        "error": j.error,
        "queued_at": j.queued_at.isoformat() if j.queued_at else None,
        "started_at": j.started_at.isoformat() if j.started_at else None,
        "completed_at": j.completed_at.isoformat() if j.completed_at else None,
    }


@router.get("")
def list_chat_jobs(
    job_status: str | None = None,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles(SYS_ADMIN)),
) -> dict:
    stmt = select(ChatJob).order_by(ChatJob.queued_at.desc())
    if job_status:
        stmt = stmt.where(ChatJob.status == job_status)
    jobs = db.execute(stmt).scalars().all()
    return envelope([_job_view(j) for j in jobs], count=len(jobs))
