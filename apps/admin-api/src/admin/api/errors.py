"""오류 로그 API — admin-web '시스템 › 오류 로그' (TDD §7.5). SYS_ADMIN 전용.

1. GET /api/v1/errors        DB 에 기록된 오류 통합 목록 (대화 작업 · 색인 작업 · 관리 API)
2. GET /api/v1/errors/logs   선택한 오류 시각 전후의 관련 서비스 파드 로그 (allowlist·마스킹·감사)

kubectl 없이 "⚠️ 답변 생성 중 오류" 의 원인(예: reranker ReadTimeout Traceback)까지 추적하기 위한 화면.
"""

from __future__ import annotations

import datetime as dt
import re
import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from admin.api.responses import api_error, envelope
from admin.core.config import get_settings
from admin.core.rbac import SYS_ADMIN, Principal, require_roles
from admin.db.models import (
    AuditLog,
    ChatChannel,
    ChatJob,
    ChatPost,
    Document,
    DocumentVersion,
    IndexJob,
)
from admin.db.session import get_db
from admin.services.pod_logs import (
    INDEX_JOB_LABEL,
    PodLogReader,
    PodLogsDisabled,
    PodLogsError,
    collect_logs,
    log_targets,
    provide_pod_log_reader,
)

router = APIRouter(prefix="/api/v1/errors", tags=["errors"])

SOURCES = ("chat", "index", "admin")
QUESTION_EXCERPT = 80

# chat_jobs.error 의 대상 URL → 로그를 볼 서비스 (rag-worker 가 남긴 "[http://...]" 포함)
_URL_SERVICE = (
    (re.compile(r"reranker-api"), "reranker-api"),
    (re.compile(r"embedding-api"), "embedding-api"),
    (re.compile(r"vllm-service|/v1/chat/completions"), "vllm"),
    (re.compile(r"qdrant"), "rag-worker"),
)


def guess_service(source: str, error: str | None) -> str:
    if source == "index":
        return "parser-indexer"
    if source == "admin":
        return "admin-api"
    for pattern, svc in _URL_SERVICE:
        if error and pattern.search(error):
            return svc
    return "rag-worker"


def _utc(v: dt.datetime | None) -> dt.datetime | None:
    if v is None:
        return None
    return v if v.tzinfo else v.replace(tzinfo=dt.UTC)  # SQLite 는 tz 를 잃는다


def _iso(v: dt.datetime | None) -> str | None:
    v = _utc(v)
    return v.isoformat() if v else None


@router.get("")
def list_errors(
    source: str | None = Query(default=None, description="chat | index | admin (비우면 전체)"),
    hours: int = Query(default=24, ge=1, le=24 * 30),
    limit: int = Query(default=200, ge=1, le=1000),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles(SYS_ADMIN)),
) -> dict:
    if source is not None and source not in SOURCES:
        raise api_error(
            "INVALID_SOURCE",
            "source 는 chat/index/admin 중 하나입니다.",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    since = dt.datetime.now(dt.UTC) - dt.timedelta(hours=hours)
    items: list[dict] = []

    if source in (None, "chat"):
        rows = db.execute(
            select(ChatJob, ChatPost.message, ChatChannel.name)
            .outerjoin(ChatPost, ChatPost.id == ChatJob.post_id)
            .outerjoin(ChatChannel, ChatChannel.id == ChatPost.channel_id)
            .where(ChatJob.status.in_(("FAILED", "DELIVERY_FAILED")), ChatJob.queued_at >= since)
            .order_by(ChatJob.queued_at.desc())
            .limit(limit)
        ).all()
        for job, message, channel in rows:
            question = (message or "").strip().replace("\n", " ")
            if len(question) > QUESTION_EXCERPT:
                question = question[:QUESTION_EXCERPT] + "…"
            error = job.error or (
                "답변은 생성됐으나 실시간 전송 실패 — 사용자가 채널을 다시 열면 보임"
                if job.status == "DELIVERY_FAILED"
                else None
            )
            items.append(
                {
                    "id": f"chat:{job.id}",
                    "source": "chat",
                    "ref_id": str(job.id),
                    "occurred_at": _iso(job.completed_at or job.started_at or job.queued_at),
                    "status": job.status,
                    "error": error,
                    "summary": f"#{channel} · {question}" if channel else question or "(질문 없음)",
                    "context": {"channel": channel, "question": question},
                    "service": guess_service("chat", job.error),
                }
            )

    if source in (None, "index"):
        rows = db.execute(
            select(IndexJob, Document.title, Document.id)
            .join(DocumentVersion, DocumentVersion.id == IndexJob.document_version_id)
            .join(Document, Document.id == DocumentVersion.document_id)
            .where(
                IndexJob.created_at >= since,
                or_(
                    IndexJob.status == "FAILED",
                    (IndexJob.status == "PENDING") & IndexJob.error.like("TRIGGER_FAILED%"),
                ),
            )
            .order_by(IndexJob.created_at.desc())
            .limit(limit)
        ).all()
        for job, title, doc_id in rows:
            items.append(
                {
                    "id": f"index:{job.id}",
                    "source": "index",
                    "ref_id": str(job.id),
                    "occurred_at": _iso(job.completed_at or job.started_at or job.created_at),
                    "status": job.status,
                    "error": job.error,
                    "summary": f"{title} · stage={job.stage or '-'}",
                    "context": {"document_id": str(doc_id), "title": title, "stage": job.stage},
                    "service": "parser-indexer",
                }
            )

    if source in (None, "admin"):
        rows = db.execute(
            select(AuditLog)
            .where(AuditLog.result.in_(("ERROR", "DENIED")), AuditLog.ts >= since)
            .order_by(AuditLog.ts.desc())
            .limit(limit)
        ).scalars()
        for a in rows:
            code = (a.detail or {}).get("status_code")
            items.append(
                {
                    "id": f"admin:{a.id}",
                    "source": "admin",
                    "ref_id": str(a.id),
                    "occurred_at": _iso(a.ts),
                    "status": a.result,
                    "error": f"HTTP {code}" if code else None,
                    "summary": f"{a.action} · {a.actor}",
                    "context": {"action": a.action, "actor": a.actor, "status_code": code},
                    "service": "admin-api",
                }
            )

    items.sort(key=lambda i: i["occurred_at"] or "", reverse=True)
    items = items[:limit]
    return envelope(items, count=len(items), services=sorted(log_targets(get_settings())))


@router.get("/logs")
def error_logs(
    service: str,
    at: dt.datetime,
    before_min: int = Query(default=5, ge=0, le=60),
    after_min: int = Query(default=2, ge=0, le=60),
    index_job_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles(SYS_ADMIN)),
    reader: PodLogReader = Depends(provide_pod_log_reader),
) -> dict:
    """allowlist 서비스의 파드 로그 [at-before, at+after]. 줄마다 마스킹, Pod 당 크기 상한, 열람 감사."""
    settings = get_settings()
    targets = log_targets(settings)
    if service not in targets:
        raise api_error(
            "UNKNOWN_SERVICE",
            "로그를 조회할 수 없는 서비스입니다.",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            allowed=sorted(targets),
        )
    namespace, selector = targets[service]
    if service == "parser-indexer":
        if index_job_id is None:
            raise api_error(
                "INDEX_JOB_ID_REQUIRED",
                "색인 로그는 index_job_id 가 필요합니다.",
                status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        selector = f"{INDEX_JOB_LABEL}={index_job_id}"

    at_utc = _utc(at)
    assert at_utc is not None
    since = at_utc - dt.timedelta(minutes=before_min)
    until = at_utc + dt.timedelta(minutes=after_min)
    try:
        pods = collect_logs(reader, namespace, selector, since=since, until=until)
    except PodLogsDisabled as exc:
        raise api_error(
            "POD_LOGS_DISABLED",
            "파드 로그 조회가 비활성화되어 있습니다 (POD_LOG_ACCESS=k8s 및 chart podLogs.enabled 필요). kubectl logs 를 사용하세요.",
            status.HTTP_503_SERVICE_UNAVAILABLE,
        ) from exc
    except PodLogsError as exc:
        raise api_error(
            "POD_LOGS_UNAVAILABLE",
            f"파드 로그를 가져오지 못했습니다: {exc}",
            status.HTTP_502_BAD_GATEWAY,
        ) from exc

    # 로그에는 질문 원문·내부 주소가 포함될 수 있다 — GET 이라 미들웨어가 기록하지 않으므로 명시 감사
    db.add(
        AuditLog(
            actor=principal.login_id,
            action="ERROR_LOG_VIEW",
            target=service,
            result="OK",
            detail={"at": at_utc.isoformat(), "pods": [p.pod for p in pods]},
        )
    )
    db.commit()

    reason = None
    if not pods:
        reason = (
            "색인 Job Pod 가 없습니다 — 완료/실패 1시간 후 자동 삭제되어 로그도 함께 사라집니다."
            if service == "parser-indexer"
            else "대상 Pod 가 없습니다."
        )
    return envelope(
        {
            "service": service,
            "namespace": namespace,
            "since": since.isoformat(),
            "until": until.isoformat(),
            "reason": reason,
            "pods": [
                {
                    "pod": p.pod,
                    "previous": p.previous,
                    "truncated": p.truncated,
                    "lines": [{"ts": ln.ts, "text": ln.text} for ln in p.lines],
                }
                for p in pods
            ],
        }
    )
