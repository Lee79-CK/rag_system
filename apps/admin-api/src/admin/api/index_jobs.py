"""색인 작업 API — admin-web '지식 관리 › 색인 작업' (PRD §17.8, FR-IDX-005/008, TDD §7.5).

1. GET  /api/v1/index-jobs             목록 (문서 제목·버전 조인, 상태/문서 필터, 최신순)
2. GET  /api/v1/index-jobs/{id}        단건
3. POST /api/v1/index-jobs/{id}/retry  실패·취소·트리거 실패 Job 재시도 → 새 Job

재시도는 documents 의 재색인 경로(_start_index)를 그대로 쓴다 — 실행 중 409, 대기 Job 교체 등
같은 문서 중복 색인 방지 규칙을 한 곳에서만 유지하기 위해서다. 원 Job 은 이력으로 남긴다.
조회(GET)는 DB 를 바꾸지 않는다: 오래 RUNNING 에 남은 Job 은 `stale` 로만 표시하고,
FAILED 정리는 기존대로 재색인/PATCH 시 _inflight_jobs 가 수행한다.
"""

from __future__ import annotations

import datetime as dt
import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from admin.api.documents import _get_doc, _reject_deleted, _start_index
from admin.api.responses import api_error, envelope
from admin.core.config import get_settings
from admin.core.rbac import DOC_ADMIN, SYS_ADMIN, Principal, require_roles
from admin.db.models import Document, DocumentVersion, IndexJob
from admin.db.session import get_db
from admin.services.index_trigger import IndexJobTrigger, provide_index_trigger

router = APIRouter(prefix="/api/v1/index-jobs", tags=["index-jobs"])

JOB_STATUSES = ("PENDING", "RUNNING", "COMPLETED", "FAILED", "CANCELLED")


def _aware(ts: dt.datetime | None) -> dt.datetime | None:
    if ts is not None and ts.tzinfo is None:  # SQLite 는 tz 를 잃는다
        return ts.replace(tzinfo=dt.UTC)
    return ts


def _iso(ts: dt.datetime | None) -> str | None:
    ts = _aware(ts)
    return ts.isoformat() if ts else None


def _job_view(
    job: IndexJob, version: DocumentVersion, doc: Document, stale_before: dt.datetime
) -> dict:
    started = _aware(job.started_at)
    return {
        "id": str(job.id),
        "document_id": str(doc.id),
        "document_title": doc.title,
        "version": version.version,
        "document_version_id": str(version.id),
        "status": job.status,
        "stage": job.stage,
        "progress": job.progress,
        "chunk_count": job.chunk_count,
        "vector_count": job.vector_count,
        "error": job.error,
        "created_at": _iso(job.created_at),
        "started_at": _iso(job.started_at),
        "completed_at": _iso(job.completed_at),
        "stale": job.status == "RUNNING" and started is not None and started < stale_before,
    }


def _stale_before() -> dt.datetime:
    return dt.datetime.now(dt.UTC) - dt.timedelta(minutes=get_settings().index_job_stale_minutes)


def _query():
    return (
        select(IndexJob, DocumentVersion, Document)
        .join(DocumentVersion, DocumentVersion.id == IndexJob.document_version_id)
        .join(Document, Document.id == DocumentVersion.document_id)
    )


def _retryable(job: IndexJob) -> bool:
    if job.status in ("FAILED", "CANCELLED"):
        return True
    # 트리거 실패로 영영 실행되지 않을 대기 Job
    return job.status == "PENDING" and (job.error or "").startswith("TRIGGER_FAILED")


@router.get("")
def list_index_jobs(
    status_: str | None = Query(default=None, alias="status"),
    document_id: uuid.UUID | None = None,
    limit: int = Query(default=200, ge=1, le=500),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles(SYS_ADMIN, DOC_ADMIN)),
) -> dict:
    stmt = _query()
    if status_:
        wanted = status_.upper()
        if wanted not in JOB_STATUSES:
            raise api_error(
                "INVALID_STATUS",
                "알 수 없는 색인 작업 상태입니다.",
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                allowed=list(JOB_STATUSES),
            )
        stmt = stmt.where(IndexJob.status == wanted)
    if document_id is not None:
        stmt = stmt.where(Document.id == document_id)
    stmt = stmt.order_by(IndexJob.created_at.desc()).limit(limit)
    stale_before = _stale_before()
    items = [_job_view(j, v, d, stale_before) for j, v, d in db.execute(stmt).all()]
    return envelope(items, count=len(items))


def _get_row(db: Session, job_id: uuid.UUID) -> tuple[IndexJob, DocumentVersion, Document]:
    row = db.execute(_query().where(IndexJob.id == job_id)).first()
    if row is None:
        raise api_error("NOT_FOUND", "색인 작업을 찾을 수 없습니다.", status.HTTP_404_NOT_FOUND)
    return row[0], row[1], row[2]


@router.get("/{job_id}")
def get_index_job(
    job_id: uuid.UUID,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles(SYS_ADMIN, DOC_ADMIN)),
) -> dict:
    job, version, doc = _get_row(db, job_id)
    return envelope(_job_view(job, version, doc, _stale_before()))


@router.post("/{job_id}/retry", status_code=status.HTTP_202_ACCEPTED)
def retry_index_job(
    job_id: uuid.UUID,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles(SYS_ADMIN, DOC_ADMIN)),
    trigger: IndexJobTrigger = Depends(provide_index_trigger),
) -> dict:
    job, version, doc = _get_row(db, job_id)
    if not _retryable(job):
        raise api_error(
            "INDEX_JOB_NOT_RETRYABLE",
            "실패·취소되었거나 트리거에 실패한 작업만 재시도할 수 있습니다.",
            status.HTTP_409_CONFLICT,
            status=job.status,
        )
    doc = _get_doc(db, doc.id)
    if doc.active_version_id != version.id:
        # 옛 버전을 다시 색인하면 활성 버전의 검색 데이터를 덮어쓴다
        raise api_error(
            "INDEX_JOB_SUPERSEDED",
            "이전 버전의 작업입니다. 문서 화면에서 현재 버전을 재색인하세요.",
            status.HTTP_409_CONFLICT,
            active_version_id=str(doc.active_version_id) if doc.active_version_id else None,
        )
    _reject_deleted(doc, "재시도")
    if doc.status == "INACTIVE":
        raise api_error(
            "DOCUMENT_INACTIVE",
            "비활성 문서는 재시도할 수 없습니다. 먼저 활성화하세요.",
            status.HTTP_409_CONFLICT,
        )
    return envelope(_start_index(db, doc, trigger))
