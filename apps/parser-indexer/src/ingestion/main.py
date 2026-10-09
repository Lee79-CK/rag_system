"""parser-indexer CLI 진입점 — §7.7 10-step 파이프라인.

실행: `python -m ingestion.main --index-job-id <uuid>`

DB(repo) / Qdrant client / Embedder를 주입 가능하게 구성하여 테스트가 fake를
전달할 수 있다. 실패는 index_jobs status=FAILED(+error/stage)로 기록한다.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Protocol

from rag_observability import configure_logging, get_logger

from ingestion.chunker.chunker import Chunk, chunk_document
from ingestion.core.config import Settings, get_settings
from ingestion.db import JobContext, JobRepository
from ingestion.indexer.embedder import Embedder
from ingestion.indexer.qdrant_client_factory import create_qdrant_client
from ingestion.indexer.qdrant_upserter import DocMetadata, QdrantUpserter
from ingestion.parser.dispatcher import parse_document
from ingestion.parser.errors import IndexFailed, ParseFailed
from ingestion.validator import validate_index

logger = get_logger(__name__)


class SupportsJobRepo(Protocol):
    def load_job(self, index_job_id: str) -> JobContext: ...
    def mark_running(self, index_job_id: str) -> None: ...
    def set_stage(self, index_job_id: str, stage: str, progress: float) -> None: ...
    def set_counts(self, index_job_id: str, *, chunk_count: int, vector_count: int) -> None: ...
    def mark_completed(self, index_job_id: str) -> None: ...
    def mark_cancelled(self, index_job_id: str, *, reason: str) -> None: ...
    def mark_failed(self, index_job_id: str, *, stage: str | None, error: str) -> None: ...
    def activate_version(self, document_id: str, version_id: str) -> None: ...


class SupportsEmbedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


def _resolve_path(settings: Settings, file_path: str) -> Path:
    """file_path가 절대경로면 그대로, 상대면 DOCUMENT_STORAGE_PATH 기준."""
    p = Path(file_path)
    if p.is_absolute():
        return p
    return Path(settings.document_storage_path) / file_path


def run_index_job(
    index_job_id: str,
    *,
    repo: SupportsJobRepo,
    qdrant_client: object,
    embedder: SupportsEmbedder,
    settings: Settings,
) -> int:
    """§7.7 10-step 파이프라인 실행. 반환: upsert된 point 수."""
    stage: str | None = None
    try:
        # 1. index_jobs 로딩 → stage=PARSING
        ctx = repo.load_job(index_job_id)
        if ctx.document_status in ("INACTIVE", "DELETED"):
            # 비활성/삭제 후 실행된 Job(대기 중이던 K8s Job 등) — 색인하면 is_active=true upsert +
            # activate_version 으로 문서가 되살아난다. 아무것도 쓰지 않고 종료(성공 종료 → Job 재시도 없음).
            repo.mark_cancelled(index_job_id, reason=f"CANCELLED: document {ctx.document_status}")
            logger.info("index_cancelled", index_job_id=index_job_id, status=ctx.document_status)
            return 0
        repo.mark_running(index_job_id)
        stage = "PARSING"
        repo.set_stage(index_job_id, stage, 0.05)

        # 2. Parser Dispatcher
        path = _resolve_path(settings, ctx.file_path)
        parsed = parse_document(
            path,
            document_id=ctx.document_id,
            version_id=ctx.document_version_id,
            ocr_enabled=settings.ocr_enabled,
            pdf_text_engine=settings.pdf_text_engine,
        )
        logger.info("parsed", index_job_id=index_job_id, stats=parsed.stats)

        # 3. → stage=CHUNKING
        stage = "CHUNKING"
        repo.set_stage(index_job_id, stage, 0.25)
        chunks: list[Chunk] = chunk_document(
            parsed,
            chunk_size_tokens=settings.chunk_size,
            chunk_overlap_tokens=settings.chunk_overlap,
            chars_per_token=settings.chars_per_token,
            min_chunk_tokens=settings.min_chunk_tokens,
            default_title=ctx.title,
        )
        if not chunks:
            raise IndexFailed("생성된 chunk 없음", code="NO_CHUNKS")
        repo.set_counts(index_job_id, chunk_count=len(chunks), vector_count=0)

        # 5. Metadata + ACL
        meta = DocMetadata(
            document_id=ctx.document_id,
            document_version_id=ctx.document_version_id,
            source_file=Path(ctx.file_path).name,
            title=ctx.title,
            category=ctx.category,
            department=ctx.department,
            security_level=ctx.security_level,
            allowed_channel_ids=ctx.allowed_channel_ids,
        )

        # 6. stage=EMBEDDING
        stage = "EMBEDDING"
        repo.set_stage(index_job_id, stage, 0.45)
        vectors = embedder.embed([c.text for c in chunks])

        # 7. stage=UPSERTING (멱등)
        stage = "UPSERTING"
        repo.set_stage(index_job_id, stage, 0.7)
        upserter = QdrantUpserter(qdrant_client, settings.qdrant_collection)
        point_count = upserter.upsert(chunks, vectors, meta)
        repo.set_counts(index_job_id, chunk_count=len(chunks), vector_count=point_count)

        # 8. stage=VALIDATING
        stage = "VALIDATING"
        repo.set_stage(index_job_id, stage, 0.85)
        qdrant_count = upserter.count_by_version(ctx.document_version_id)
        validate_index(
            qdrant_client,
            settings.qdrant_collection,
            ctx.document_version_id,
            pg_chunk_count=len(chunks),
            qdrant_count=qdrant_count,
            sample_vectors=vectors,
        )

        # 9. 버전 활성화 + 구버전 비활성
        stage = "ACTIVATING"
        upserter.deactivate_other_versions(ctx.document_id, ctx.document_version_id)
        repo.activate_version(ctx.document_id, ctx.document_version_id)

        # 10. 완료
        repo.mark_completed(index_job_id)
        logger.info("index_completed", index_job_id=index_job_id, points=point_count)
        return point_count

    except (ParseFailed, IndexFailed) as exc:
        code = getattr(exc, "code", "UNKNOWN")
        logger.error("index_failed", index_job_id=index_job_id, stage=stage, code=code)
        repo.mark_failed(index_job_id, stage=stage, error=str(exc))
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error("index_error", index_job_id=index_job_id, stage=stage, error=str(exc))
        repo.mark_failed(index_job_id, stage=stage, error=str(exc))
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ingestion.main", description="문서 파싱+색인 배치")
    parser.add_argument("--index-job-id", required=True, help="index_jobs.id (UUID)")
    args = parser.parse_args(argv)

    settings = get_settings()
    configure_logging("parser-indexer")

    repo = JobRepository.from_url(settings.sqlalchemy_url())
    qdrant_client = create_qdrant_client(settings.qdrant_url, timeout=settings.qdrant_timeout)
    embedder = Embedder(
        settings.embedding_api_url,
        batch_size=settings.embedding_max_batch,
        timeout=settings.embedding_timeout,
    )
    try:
        run_index_job(
            args.index_job_id,
            repo=repo,
            qdrant_client=qdrant_client,
            embedder=embedder,
            settings=settings,
        )
    except Exception:  # noqa: BLE001
        return 1
    finally:
        embedder.close()
        qdrant_client.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
