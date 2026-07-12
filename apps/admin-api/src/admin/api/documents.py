"""문서 관리 API — docs/TDD.md §7.5 (§9.5).

업로드(크기/확장자/sha256 중복검사 FR-DOC-002/003), 목록, 상세, 버전,
재색인(index_jobs INSERT + Job 트리거 stub), 비활성화/삭제.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from rag_common import sha256_hex
from sqlalchemy import select
from sqlalchemy.orm import Session

from admin.api.responses import api_error, envelope
from admin.core.config import get_settings
from admin.core.rbac import DOC_ADMIN, SYS_ADMIN, Principal, require_roles
from admin.db.models import Document, DocumentVersion, IndexJob
from admin.db.session import get_db
from admin.services.storage import NFSStorage

router = APIRouter(prefix="/api/v1/documents", tags=["documents"])

# FR-DOC-002 확장자 allowlist.
ALLOWED_EXTENSIONS = frozenset({"pdf", "docx", "pptx", "xlsx", "txt", "md", "html"})


def _ext(filename: str | None) -> str:
    if not filename or "." not in filename:
        return ""
    return filename.rsplit(".", 1)[-1].lower()


def _storage() -> NFSStorage:
    return NFSStorage(get_settings().document_storage_path)


def _doc_view(doc: Document) -> dict:
    return {
        "id": str(doc.id),
        "title": doc.title,
        "category": doc.category,
        "department": doc.department,
        "security_level": doc.security_level,
        "status": doc.status,
        "active_version_id": str(doc.active_version_id) if doc.active_version_id else None,
        "created_at": doc.created_at.isoformat() if doc.created_at else None,
    }


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
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles(SYS_ADMIN, DOC_ADMIN)),
) -> dict:
    settings = get_settings()
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
        raise api_error(
            "DUPLICATE_DOCUMENT",
            "이미 등록된 문서와 내용이 동일합니다 (중복 업로드).",
            status.HTTP_409_CONFLICT,
            existing_document_id=str(existing.document_id),
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
    db.commit()

    return envelope({"document": _doc_view(doc), "version": _version_view(version)})


@router.get("")
def list_documents(
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles(SYS_ADMIN, DOC_ADMIN)),
) -> dict:
    docs = db.execute(select(Document).order_by(Document.created_at.desc())).scalars().all()
    return envelope([_doc_view(d) for d in docs], count=len(docs))


@router.get("/{document_id}")
def get_document(
    document_id: uuid.UUID,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles(SYS_ADMIN, DOC_ADMIN)),
) -> dict:
    doc = db.get(Document, document_id)
    if doc is None:
        raise api_error("NOT_FOUND", "문서를 찾을 수 없습니다.", status.HTTP_404_NOT_FOUND)
    return envelope(_doc_view(doc))


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
) -> dict:
    doc = db.get(Document, document_id)
    if doc is None:
        raise api_error("NOT_FOUND", "문서를 찾을 수 없습니다.", status.HTTP_404_NOT_FOUND)
    if doc.active_version_id is None:
        raise api_error(
            "NO_ACTIVE_VERSION",
            "활성 버전이 없어 재색인할 수 없습니다.",
            status.HTTP_409_CONFLICT,
        )

    job = IndexJob(document_version_id=doc.active_version_id, status="PENDING", stage=None)
    db.add(job)
    doc.status = "INDEXING"
    db.commit()

    # 색인 Job 트리거 (stub): 폐쇄망 K8s Job / DB polling worker가 소비 (§7.5, FR-IDX-*).
    _trigger_index_job(str(job.id))

    return envelope({"index_job_id": str(job.id), "status": job.status})


def _trigger_index_job(index_job_id: str) -> None:
    """K8s Job 생성 트리거 stub. PoC fallback은 DB polling worker (§7.5)."""
    # 외부 네트워크/K8s API 호출 없음 — index_jobs row가 트리거 신호로 기능한다.
    return None


@router.post("/{document_id}/deactivate")
def deactivate_document(
    document_id: uuid.UUID,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles(SYS_ADMIN, DOC_ADMIN)),
) -> dict:
    doc = db.get(Document, document_id)
    if doc is None:
        raise api_error("NOT_FOUND", "문서를 찾을 수 없습니다.", status.HTTP_404_NOT_FOUND)
    doc.status = "INACTIVE"
    db.commit()
    return envelope(_doc_view(doc))


@router.delete("/{document_id}")
def delete_document(
    document_id: uuid.UUID,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles(SYS_ADMIN, DOC_ADMIN)),
) -> dict:
    doc = db.get(Document, document_id)
    if doc is None:
        raise api_error("NOT_FOUND", "문서를 찾을 수 없습니다.", status.HTTP_404_NOT_FOUND)
    # 논리 삭제: 검색 제외는 is_active=false payload set(야간 배치)와 정합 (FR-DOC-008).
    doc.status = "DELETED"
    db.commit()
    return envelope({"id": str(document_id), "status": doc.status})
