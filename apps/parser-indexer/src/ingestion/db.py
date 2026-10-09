"""index_jobs / documents 접근 — SQLAlchemy Core (docs/TDD.md §5, §7.7).

ORM 모델은 admin-api 소유(§5)다. parser-indexer는 apps/* 간 import 금지 규칙(§2.1)에
따라 원시 SQL(text)로 필요한 컬럼만 읽고 상태만 갱신한다.

테스트는 이 클래스 대신 동일 인터페이스의 fake를 주입할 수 있다(main.run_index_job).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime

from rag_observability import get_logger
from sqlalchemy import Engine, create_engine, text

from ingestion.core.config import Settings
from ingestion.slots import acquire_slot

logger = get_logger(__name__)


@dataclass
class JobContext:
    """색인 Job 실행에 필요한 문서/버전/ACL 정보 (§7.7 step 1, 5)."""

    index_job_id: str
    document_version_id: str
    document_id: str
    version: int
    file_path: str
    title: str
    category: str | None = None
    department: str | None = None
    security_level: str = "INTERNAL"
    allowed_channel_ids: list[str] = field(default_factory=list)
    document_status: str = "INDEXING"
    job_status: str = "PENDING"


class JobRepository:
    """index_jobs 상태 전이 + 문서 메타/ACL 조회."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    @classmethod
    def from_url(cls, url: str) -> JobRepository:
        return cls(create_engine(url, pool_pre_ping=True))

    def load_job(self, index_job_id: str) -> JobContext:
        with self._engine.connect() as conn:
            row = (
                conn.execute(
                    text(
                        """
                    SELECT ij.id AS index_job_id,
                           ij.status AS job_status,
                           ij.document_version_id,
                           dv.document_id,
                           dv.version,
                           dv.file_path,
                           d.title,
                           d.category,
                           d.department,
                           d.security_level,
                           d.status AS document_status
                    FROM index_jobs ij
                    JOIN document_versions dv ON dv.id = ij.document_version_id
                    JOIN documents d ON d.id = dv.document_id
                    WHERE ij.id = :jid
                    """
                    ),
                    {"jid": index_job_id},
                )
                .mappings()
                .first()
            )
            if row is None:
                raise LookupError(f"index_job not found: {index_job_id}")

            acl_rows = (
                conn.execute(
                    text(
                        """
                    SELECT channel_id
                    FROM document_channel_acl
                    WHERE document_id = :did AND access_type = 'ALLOW'
                    """
                    ),
                    {"did": row["document_id"]},
                )
                .scalars()
                .all()
            )

        return JobContext(
            index_job_id=str(row["index_job_id"]),
            document_version_id=str(row["document_version_id"]),
            document_id=str(row["document_id"]),
            version=int(row["version"]),
            file_path=str(row["file_path"]),
            title=str(row["title"]),
            category=row["category"],
            department=row["department"],
            security_level=str(row["security_level"] or "INTERNAL"),
            allowed_channel_ids=[str(c) for c in acl_rows],
            document_status=str(row["document_status"]),
            job_status=str(row["job_status"]),
        )

    @contextmanager
    def index_slot(self, index_job_id: str, settings: Settings) -> Iterator[int]:
        """동시 색인 슬롯(advisory lock)을 잡고 Job 이 끝날 때까지 유지한다.

        전용 연결을 Job 동안 열어 둔다. 조회마다 commit 해 'idle in transaction' 을 남기지 않고,
        끝나면 명시적으로 unlock 한다(풀에 반환된 연결에 세션 lock 이 남지 않게).
        """
        conn = self._engine.connect()
        held: list[int] = []

        def _try(key: int) -> bool:
            ok = bool(conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": key}).scalar())
            conn.commit()
            if ok:
                held.append(key)
            return ok

        last_log = [-1.0]

        def _on_wait(elapsed: float) -> None:
            # 첫 대기 때 stage=WAITING 표시, 로그는 60초 간격
            if last_log[0] < 0:
                self._mark_waiting(index_job_id)
            if last_log[0] < 0 or elapsed - last_log[0] >= 60:
                last_log[0] = elapsed
                logger.info(
                    "index_slot_waiting",
                    index_job_id=index_job_id,
                    waited_s=int(elapsed),
                    max_parallel=settings.index_max_parallel,
                )

        try:
            slot = acquire_slot(
                _try,
                max_parallel=settings.index_max_parallel,
                poll_seconds=settings.index_slot_poll_seconds,
                timeout_seconds=settings.index_slot_wait_timeout_seconds,
                on_wait=_on_wait,
            )
            logger.info("index_slot_acquired", index_job_id=index_job_id, slot=slot)
            yield slot
        finally:
            try:
                for key in held:
                    conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": key})
                conn.commit()
            finally:
                conn.close()

    def _mark_waiting(self, index_job_id: str) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                text("UPDATE index_jobs SET stage='WAITING' WHERE id=:jid AND status='PENDING'"),
                {"jid": index_job_id},
            )

    def mark_running(self, index_job_id: str) -> None:
        self._update(
            index_job_id,
            "UPDATE index_jobs SET status='RUNNING', started_at=:now, progress=0 WHERE id=:jid",
        )

    def set_stage(self, index_job_id: str, stage: str, progress: float) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                text("UPDATE index_jobs SET stage=:stage, progress=:p WHERE id=:jid"),
                {"stage": stage, "p": progress, "jid": index_job_id},
            )

    def set_counts(self, index_job_id: str, *, chunk_count: int, vector_count: int) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                text("UPDATE index_jobs SET chunk_count=:c, vector_count=:v WHERE id=:jid"),
                {"c": chunk_count, "v": vector_count, "jid": index_job_id},
            )

    def mark_completed(self, index_job_id: str) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE index_jobs SET status='COMPLETED', stage='DONE', progress=1.0, "
                    "completed_at=:now WHERE id=:jid"
                ),
                {"now": datetime.now(UTC), "jid": index_job_id},
            )

    def mark_cancelled(self, index_job_id: str, *, reason: str) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE index_jobs SET status='CANCELLED', error=:err, completed_at=:now "
                    "WHERE id=:jid"
                ),
                {"err": reason[:2000], "now": datetime.now(UTC), "jid": index_job_id},
            )

    def mark_failed(self, index_job_id: str, *, stage: str | None, error: str) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE index_jobs SET status='FAILED', stage=:stage, error=:err, "
                    "completed_at=:now WHERE id=:jid"
                ),
                {
                    "stage": stage,
                    "err": error[:2000],
                    "now": datetime.now(UTC),
                    "jid": index_job_id,
                },
            )

    def activate_version(self, document_id: str, version_id: str) -> None:
        """document_versions.status=ACTIVE + documents.active_version_id 전환 (§7.7 step 9)."""
        with self._engine.begin() as conn:
            conn.execute(
                text("UPDATE document_versions SET status='ACTIVE' WHERE id=:vid"),
                {"vid": version_id},
            )
            conn.execute(
                text(
                    "UPDATE document_versions SET status='SUPERSEDED' "
                    "WHERE document_id=:did AND id<>:vid AND status='ACTIVE'"
                ),
                {"did": document_id, "vid": version_id},
            )
            conn.execute(
                text(
                    "UPDATE documents SET active_version_id=:vid, status='ACTIVE', "
                    "updated_at=:now WHERE id=:did"
                ),
                {"vid": version_id, "did": document_id, "now": datetime.now(UTC)},
            )

    def _update(self, index_job_id: str, sql: str) -> None:
        with self._engine.begin() as conn:
            conn.execute(text(sql), {"now": datetime.now(UTC), "jid": index_job_id})
