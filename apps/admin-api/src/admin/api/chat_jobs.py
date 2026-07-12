"""Chat Job 관리 API — docs/TDD.md §7.5.

목록 + POST /{id}/retry-delivery (Dead Letter 수동 재시도 stub, §7.1.2 step6).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from admin.api.responses import api_error, envelope
from admin.core.rbac import SYS_ADMIN, Principal, require_roles
from admin.db.models import ChatJob, MattermostDelivery
from admin.db.session import get_db

router = APIRouter(prefix="/api/v1/chat-jobs", tags=["chat-jobs"])


def _job_view(j: ChatJob) -> dict:
    return {
        "id": str(j.id),
        "event_id": str(j.event_id) if j.event_id else None,
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


@router.post("/{job_id}/retry-delivery", status_code=status.HTTP_202_ACCEPTED)
def retry_delivery(
    job_id: uuid.UUID,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles(SYS_ADMIN)),
) -> dict:
    """Dead Letter된 delivery를 수동 재시도 대기 상태로 되돌린다 (stub, FR-MM-013)."""
    job = db.get(ChatJob, job_id)
    if job is None:
        raise api_error("NOT_FOUND", "Chat Job을 찾을 수 없습니다.", status.HTTP_404_NOT_FOUND)

    deliveries = (
        db.execute(
            select(MattermostDelivery)
            .where(MattermostDelivery.chat_job_id == job_id)
            .order_by(MattermostDelivery.created_at.desc())
        )
        .scalars()
        .all()
    )
    if not deliveries:
        raise api_error(
            "NO_DELIVERY",
            "재시도할 delivery 기록이 없습니다.",
            status.HTTP_409_CONFLICT,
        )

    latest = deliveries[0]
    latest.status = "PENDING"
    latest.updated_at = datetime.now(UTC)
    job.status = "DELIVERY_PENDING"
    db.commit()
    # 실제 재발송은 Bridge/Worker가 PENDING delivery를 소비 (stub — 외부 호출 없음).
    return envelope(
        {"chat_job_id": str(job_id), "delivery_id": str(latest.id), "status": "PENDING"}
    )
