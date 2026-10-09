"""문서 관리 API — docs/TDD.md §7.5 (§9.5).

업로드(크기/확장자/sha256 중복검사 FR-DOC-002/003, 허용 Channel ACL FR-DOC-004), 목록, 상세, 버전,
재색인(index_jobs INSERT + Job 트리거 — admin.services.index_trigger, ADR-008), 비활성화/삭제,
허용 Channel 변경(PATCH — ACL 교체 후 자동 재색인으로 Qdrant payload 반영),
비활성화/삭제(Qdrant is_active=false 를 먼저 반영 후 상태 커밋) · 재활성화(재색인).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from pydantic import BaseModel, Field
from rag_common import sha256_hex
from rag_observability import get_logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from admin.api.responses import api_error, envelope
from admin.core.config import get_settings
from admin.core.rbac import DOC_ADMIN, SYS_ADMIN, Principal, require_roles
from admin.db.models import (
    AuditLog,
    ChatChannel,
    Document,
    DocumentChannelAcl,
    DocumentVersion,
    IndexJob,
)
from admin.db.session import get_db
from admin.services.index_trigger import IndexJobTrigger, provide_index_trigger
from admin.services.search_index import SearchIndex, SearchIndexError, provide_search_index
from admin.services.storage import NFSStorage

log = get_logger("admin.documents")

router = APIRouter(prefix="/api/v1/documents", tags=["documents"])

# FR-DOC-002 확장자 allowlist.
ALLOWED_EXTENSIONS = frozenset({"pdf", "docx", "pptx", "xlsx", "txt", "md", "html"})


def _ext(filename: str | None) -> str:
    if not filename or "." not in filename:
        return ""
    return filename.rsplit(".", 1)[-1].lower()


def _storage() -> NFSStorage:
    return NFSStorage(get_settings().document_storage_path)


class DocumentPatch(BaseModel):
    """PATCH 본문. allowed_channel_ids 는 전체 교체(빈 목록 = 어느 채널에서도 검색 안 됨)."""

    allowed_channel_ids: list[str] = Field(
        ...,
        max_length=500,
        description="허용 채널(chat_channels.id) 전체 목록 — 기존 ACL 을 대체한다.",
    )


def _doc_view(doc: Document, channel_ids: list[str]) -> dict:
    return {
        "id": str(doc.id),
        "title": doc.title,
        "category": doc.category,
        "department": doc.department,
        "security_level": doc.security_level,
        "status": doc.status,
        "active_version_id": str(doc.active_version_id) if doc.active_version_id else None,
        "allowed_channel_ids": channel_ids,
        "created_at": doc.created_at.isoformat() if doc.created_at else None,
    }


def _acl_map(db: Session, document_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[str]]:
    """document_id → 허용 channel_id 목록 (한 번의 쿼리, 목록 조회 N+1 방지)."""
    acl: dict[uuid.UUID, list[str]] = {d: [] for d in document_ids}
    if document_ids:
        rows = db.execute(
            select(DocumentChannelAcl.document_id, DocumentChannelAcl.channel_id)
            .where(
                DocumentChannelAcl.document_id.in_(document_ids),
                DocumentChannelAcl.access_type == "ALLOW",
            )
            .order_by(DocumentChannelAcl.channel_id)
        ).all()
        for did, cid in rows:
            acl[did].append(cid)
    return acl


def _channel_ids(db: Session, document_id: uuid.UUID) -> list[str]:
    return _acl_map(db, [document_id])[document_id]


def _get_doc(db: Session, document_id: uuid.UUID) -> Document:
    doc = db.get(Document, document_id)
    if doc is None:
        raise api_error("NOT_FOUND", "문서를 찾을 수 없습니다.", status.HTTP_404_NOT_FOUND)
    return doc


def _inflight_jobs(db: Session, doc: Document) -> dict[str, IndexJob]:
    """활성 버전의 PENDING/RUNNING Job (상태별 최신 1건).

    진행 판단은 documents.status 가 아니라 index_jobs 로 한다 —
    색인 실패 시 documents.status 는 INDEXING 에 남으므로(mark_failed 는 index_jobs 만 갱신).
    """
    inflight: dict[str, IndexJob] = {}
    if doc.active_version_id is not None:
        for j in db.execute(
            select(IndexJob)
            .where(
                IndexJob.document_version_id == doc.active_version_id,
                IndexJob.status.in_(("PENDING", "RUNNING")),
            )
            .order_by(IndexJob.created_at.desc())
        ).scalars():
            inflight.setdefault(j.status, j)
    return inflight


def _reject_running(inflight: dict[str, IndexJob]) -> None:
    if "RUNNING" in inflight:
        raise api_error(
            "INDEX_JOB_RUNNING",
            "색인이 진행 중입니다. 완료 후 다시 시도하세요.",
            status.HTTP_409_CONFLICT,
            index_job_id=str(inflight["RUNNING"].id),
        )


def _reject_deleted(doc: Document, action: str) -> None:
    if doc.status == "DELETED":
        raise api_error(
            "DOCUMENT_DELETED", f"삭제된 문서는 {action}할 수 없습니다.", status.HTTP_409_CONFLICT
        )


def _version_view(v: DocumentVersion) -> dict:
    return {
        "id": str(v.id),
        "document_id": str(v.document_id),
        "version": v.version,
        "hash": v.hash,
        "file_path": v.file_path,
        "file_size": v.file_size,
        "status": v.status,
        "created_at": v.created_at.isoformat() if v.created_at else None,
    }


@router.post("", status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: UploadFile = File(...),
    title: str | None = Form(default=None),
    category: str | None = Form(default=None),
    department: str | None = Form(default=None),
    security_level: str = Form(default="INTERNAL"),
    allowed_channel_ids: list[str] = Form(
        default_factory=list,
        description="허용 채널(chat_channels.id) — 반복 필드 또는 콤마 구분. 비우면 어느 채널에서도 검색되지 않는다.",
    ),
    start_indexing: bool = Form(default=False, description="true 면 업로드 직후 색인 Job 생성"),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles(SYS_ADMIN, DOC_ADMIN)),
    trigger: IndexJobTrigger = Depends(provide_index_trigger),
) -> dict:
    """업로드 + Channel ACL(document_channel_acl) 등록 (+ 선택적으로 색인 Job 생성).

    allowed_channel_ids = chat_channels.id — parser-indexer 가 Qdrant payload
    `allowed_channel_ids` 로 복사하며 build_filter() 격리의 근거가 된다 (§6.3, FR-DOC-004).
    start_indexing=true 면 index_jobs INSERT + Job 트리거 (FR-IDX-010, ADR-008).
    """
    settings = get_settings()
    channel_ids = _validated_channel_ids(db, allowed_channel_ids)
    ext = _ext(file.filename)
    if ext not in ALLOWED_EXTENSIONS:
        raise api_error(
            "UNSUPPORTED_FILE_TYPE",
            f"허용되지 않은 확장자입니다: .{ext or '(없음)'}",
            status.HTTP_400_BAD_REQUEST,
            allowed=sorted(ALLOWED_EXTENSIONS),
        )

    data = await file.read()
    if len(data) == 0:
        raise api_error(
            "EMPTY_FILE", "빈 파일은 업로드할 수 없습니다.", status.HTTP_400_BAD_REQUEST
        )
    if len(data) > settings.max_upload_bytes:
        raise api_error(
            "FILE_TOO_LARGE",
            f"파일 크기가 상한({settings.max_upload_bytes} bytes)을 초과했습니다.",
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
        )

    file_hash = sha256_hex(data)

    # FR-DOC-003: 동일 해시 중복 업로드 거부.
    existing = db.execute(
        select(DocumentVersion).where(DocumentVersion.hash == file_hash)
    ).scalar_one_or_none()
    if existing is not None:
        # 기존 문서 제목·상태를 함께 돌려준다 — admin-web 이 "기존 문서에 채널 연결"을 제안할지 판단 (DELETED 제외).
        existing_doc = db.get(Document, existing.document_id)
        raise api_error(
            "DUPLICATE_DOCUMENT",
            "이미 등록된 문서와 내용이 동일합니다 (중복 업로드).",
            status.HTTP_409_CONFLICT,
            existing_document_id=str(existing.document_id),
            existing_document_title=existing_doc.title if existing_doc else None,
            existing_document_status=existing_doc.status if existing_doc else None,
        )

    doc = Document(
        title=title or (file.filename or "untitled"),
        category=category,
        department=department,
        security_level=security_level,
        status="UPLOADED",
        created_by=uuid.UUID(principal.id) if principal.id else None,
    )
    db.add(doc)
    db.flush()  # doc.id 확보.

    file_path = _storage().save(str(doc.id), 1, file.filename or "document", data)
    version = DocumentVersion(
        document_id=doc.id,
        version=1,
        hash=file_hash,
        file_path=file_path,
        file_size=len(data),
        status="UPLOADED",
    )
    db.add(version)
    db.flush()
    doc.active_version_id = version.id

    # FR-DOC-004 / FR-RAG-004: 허용 Channel ACL. parser-indexer 가 이 행으로 allowed_channel_ids 를 채운다.
    for cid in channel_ids:
        db.add(DocumentChannelAcl(document_id=doc.id, channel_id=cid, access_type="ALLOW"))
    db.commit()

    result: dict = {
        "document": _doc_view(doc, channel_ids),
        "version": _version_view(version),
        "allowed_channel_ids": channel_ids,
    }
    if start_indexing:
        job = _create_index_job(db, doc, trigger)
        result["index_job_id"] = str(job.id)
        result["index_job_status"] = job.status
    return envelope(result)


def _create_index_job(db: Session, doc: Document, trigger: IndexJobTrigger) -> IndexJob:
    """index_jobs INSERT 후 트리거 호출. 트리거 실패는 행에 기록하고 예외로 올리지 않는다(수동 실행 가능)."""
    job = IndexJob(document_version_id=doc.active_version_id, status="PENDING", stage=None)
    db.add(job)
    doc.status = "INDEXING"
    db.commit()

    try:
        trigger.trigger(str(job.id))
    except Exception as exc:  # noqa: BLE001 — 트리거 실패는 job.error 로 노출 (FR-DOC-006)
        log.error(
            "documents.index_trigger_failed", index_job_id=str(job.id), error=type(exc).__name__
        )
        job.error = f"TRIGGER_FAILED[{trigger.name}]: {exc}"[:500]
        db.commit()
    return job


def _validated_channel_ids(db: Session, raw: list[str]) -> list[str]:
    """존재하는 chat_channels.id 만 허용 (오타·타 시스템 id 로 인한 격리 오류 방지)."""
    ids: list[str] = []
    # 반복 필드(admin-web) · 콤마 구분(curl 편의) 모두 허용
    parts = (p.strip() for x in raw if x for p in x.split(","))
    for v in dict.fromkeys(p for p in parts if p):
        try:
            ids.append(str(uuid.UUID(v)))
        except ValueError as exc:
            raise api_error(
                "INVALID_CHANNEL_ID",
                "유효하지 않은 채널 id 입니다.",
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                channel_id=v,
            ) from exc
    if ids:
        found = {
            str(c)
            for c in db.execute(
                select(ChatChannel.id).where(ChatChannel.id.in_([uuid.UUID(i) for i in ids]))
            ).scalars()
        }
        missing = [i for i in ids if i not in found]
        if missing:
            raise api_error(
                "CHANNEL_NOT_FOUND",
                "존재하지 않는 채널입니다.",
                status.HTTP_404_NOT_FOUND,
                channel_ids=missing,
            )
    return ids


@router.get("")
def list_documents(
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles(SYS_ADMIN, DOC_ADMIN)),
) -> dict:
    docs = db.execute(select(Document).order_by(Document.created_at.desc())).scalars().all()
    acl = _acl_map(db, [d.id for d in docs])
    return envelope([_doc_view(d, acl[d.id]) for d in docs], count=len(docs))


@router.get("/{document_id}")
def get_document(
    document_id: uuid.UUID,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles(SYS_ADMIN, DOC_ADMIN)),
) -> dict:
    doc = _get_doc(db, document_id)
    return envelope(_doc_view(doc, _channel_ids(db, doc.id)))


@router.patch("/{document_id}")
def update_document_channels(
    document_id: uuid.UUID,
    body: DocumentPatch,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles(SYS_ADMIN, DOC_ADMIN)),
    trigger: IndexJobTrigger = Depends(provide_index_trigger),
) -> dict:
    """허용 Channel(document_channel_acl) 전체 교체 + 변경 시 자동 재색인 (FR-DOC-004, PRD §17.8).

    격리는 Qdrant payload `allowed_channel_ids` 로만 이뤄지고 그 값은 색인 시점에 ACL 에서 복사되므로
    (parser-indexer), ACL 변경은 재색인이 끝나야 검색에 반영된다 — 제거한 채널도 그때까지는 검색된다.
    point id 가 결정론적이라 같은 활성 버전 재색인은 payload 덮어쓰기다(중복 없음).
    """
    doc = _get_doc(db, document_id)
    _reject_deleted(doc, "채널을 변경")
    new_ids = _validated_channel_ids(db, body.allowed_channel_ids)

    inflight = _inflight_jobs(db, doc)
    # 실행 중 Job 은 이미 이전 ACL 을 읽었을 수 있어, 새 Job 을 겹쳐 띄우면 늦게 끝나는 쪽 payload 가 남는다.
    _reject_running(inflight)

    before = _channel_ids(db, doc.id)
    added = [c for c in new_ids if c not in before]
    removed = [c for c in before if c not in new_ids]
    changed = bool(added or removed)

    if changed:
        for cid in removed:
            row = db.get(DocumentChannelAcl, (doc.id, cid))
            if row is not None:
                db.delete(row)
        for cid in added:
            db.add(DocumentChannelAcl(document_id=doc.id, channel_id=cid, access_type="ALLOW"))

    job: IndexJob | None = None
    trigger_name: str | None = None
    skipped: str | None = None
    if changed:
        if doc.active_version_id is None:
            skipped = "NO_ACTIVE_VERSION"
        elif doc.status not in ("ACTIVE", "INDEXING"):
            # INACTIVE 를 재색인하면 activate_version 이 ACTIVE 로 되돌린다. UPLOADED 는 아직 미색인.
            skipped = f"STATUS_{doc.status}"
        elif "PENDING" in inflight:
            job = inflight["PENDING"]  # 대기 Job 은 실행 시점에 ACL 을 읽으므로 새 ACL 이 반영된다.
            skipped = "PENDING_JOB_REUSED"

    after = sorted(new_ids)
    if changed:
        db.add(
            AuditLog(
                actor=principal.login_id,
                action="DOCUMENT_ACL_UPDATE",
                target=str(doc.id),
                result="OK",
                detail={"before": before, "after": after, "added": added, "removed": removed},
            )
        )
    db.commit()

    if changed and skipped is None:
        job = _create_index_job(db, doc, trigger)
        trigger_name = trigger.name
    log.info(
        "documents.acl_updated",
        document_id=str(doc.id),
        added=len(added),
        removed=len(removed),
        index_job_id=str(job.id) if job else None,
        reindex_skipped=skipped,
    )
    return envelope(
        {
            "document": _doc_view(doc, after),
            "changed": changed,
            "added": added,
            "removed": removed,
            "index_job": (
                {
                    "index_job_id": str(job.id),
                    "status": job.status,
                    "trigger": trigger_name,
                    "error": job.error,
                }
                if job
                else None
            ),
            "reindex_skipped_reason": skipped,
        }
    )


@router.get("/{document_id}/versions")
def list_versions(
    document_id: uuid.UUID,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles(SYS_ADMIN, DOC_ADMIN)),
) -> dict:
    doc = db.get(Document, document_id)
    if doc is None:
        raise api_error("NOT_FOUND", "문서를 찾을 수 없습니다.", status.HTTP_404_NOT_FOUND)
    versions = (
        db.execute(
            select(DocumentVersion)
            .where(DocumentVersion.document_id == document_id)
            .order_by(DocumentVersion.version.desc())
        )
        .scalars()
        .all()
    )
    return envelope([_version_view(v) for v in versions], count=len(versions))


@router.post("/{document_id}/reindex", status_code=status.HTTP_202_ACCEPTED)
def reindex_document(
    document_id: uuid.UUID,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles(SYS_ADMIN, DOC_ADMIN)),
    trigger: IndexJobTrigger = Depends(provide_index_trigger),
) -> dict:
    doc = _get_doc(db, document_id)
    _reject_deleted(doc, "재색인")
    if doc.status == "INACTIVE":
        # 재색인은 activate_version 으로 ACTIVE 를 되살린다 — 비활성 문서는 명시적 [활성화] 로만.
        raise api_error(
            "DOCUMENT_INACTIVE",
            "비활성 문서는 재색인할 수 없습니다. 먼저 활성화하세요.",
            status.HTTP_409_CONFLICT,
        )
    return envelope(_start_index(db, doc, trigger))


@router.post("/{document_id}/activate", status_code=status.HTTP_202_ACCEPTED)
def activate_document(
    document_id: uuid.UUID,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles(SYS_ADMIN, DOC_ADMIN)),
    trigger: IndexJobTrigger = Depends(provide_index_trigger),
) -> dict:
    """INACTIVE → 재색인으로 재활성화. 현재 ACL·버전으로 payload(is_active=true)를 다시 쓴다.

    payload is_active 만 되돌리지 않는 이유: 비활성 중에 바뀐 허용 채널(PATCH 는 ACL 만 저장)이
    재색인으로만 Qdrant 에 반영되기 때문.
    """
    doc = _get_doc(db, document_id)
    if doc.status != "INACTIVE":
        raise api_error(
            "DOCUMENT_NOT_INACTIVE",
            "비활성 상태인 문서만 활성화할 수 있습니다.",
            status.HTTP_409_CONFLICT,
            status=doc.status,
        )
    return envelope(_start_index(db, doc, trigger))


def _start_index(db: Session, doc: Document, trigger: IndexJobTrigger) -> dict:
    if doc.active_version_id is None:
        raise api_error(
            "NO_ACTIVE_VERSION",
            "활성 버전이 없어 재색인할 수 없습니다.",
            status.HTTP_409_CONFLICT,
        )
    job = _create_index_job(db, doc, trigger)
    return {
        "index_job_id": str(job.id),
        "status": job.status,
        "trigger": trigger.name,
        "error": job.error,
    }


def _exclude_from_search(
    db: Session, doc: Document, new_status: str, search_index: SearchIndex
) -> None:
    """검색 제외 후 상태 커밋 (FR-DOC-008).

    순서: ① RUNNING Job 이 있으면 거부(끝나면 is_active=true 로 upsert + ACTIVE 로 되돌림)
          ② Qdrant 전 point is_active=false — 실패 시 503, DB 불변
          ③ PENDING Job 은 CANCELLED (parser-indexer 도 INACTIVE/DELETED 문서 Job 은 건너뜀)
          ④ documents.status 커밋
    """
    inflight = _inflight_jobs(db, doc)
    _reject_running(inflight)
    try:
        search_index.deactivate_document(str(doc.id))
    except SearchIndexError as exc:
        raise api_error(
            "SEARCH_INDEX_UNAVAILABLE",
            "검색 색인을 갱신하지 못했습니다. 잠시 후 다시 시도하세요. (문서 상태는 변경되지 않음)",
            status.HTTP_503_SERVICE_UNAVAILABLE,
        ) from exc
    if "PENDING" in inflight:
        for j in db.execute(
            select(IndexJob).where(
                IndexJob.document_version_id == doc.active_version_id,
                IndexJob.status == "PENDING",
            )
        ).scalars():
            j.status = "CANCELLED"
            j.error = f"CANCELLED: document {new_status}"
    doc.status = new_status
    db.commit()
    log.info("documents.excluded_from_search", document_id=str(doc.id), status=new_status)


@router.post("/{document_id}/deactivate")
def deactivate_document(
    document_id: uuid.UUID,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles(SYS_ADMIN, DOC_ADMIN)),
    search_index: SearchIndex = Depends(provide_search_index),
) -> dict:
    doc = _get_doc(db, document_id)
    _reject_deleted(doc, "비활성화")
    if doc.status != "INACTIVE":
        _exclude_from_search(db, doc, "INACTIVE", search_index)
    return envelope(_doc_view(doc, _channel_ids(db, doc.id)))


@router.delete("/{document_id}")
def delete_document(
    document_id: uuid.UUID,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles(SYS_ADMIN, DOC_ADMIN)),
    search_index: SearchIndex = Depends(provide_search_index),
) -> dict:
    """논리 삭제 — 검색에서 즉시 제외(is_active=false). 원본 파일·point 는 보존(감사·복구용)."""
    doc = _get_doc(db, document_id)
    if doc.status != "DELETED":
        _exclude_from_search(db, doc, "DELETED", search_index)
    return envelope({"id": str(document_id), "status": doc.status})
