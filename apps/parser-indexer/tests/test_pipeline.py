"""main.run_index_job 파이프라인 테스트 — 주입된 fake로 hermetic 실행 (§7.7)."""

from __future__ import annotations

import contextlib

from ingestion.core.config import Settings
from ingestion.db import JobContext
from ingestion.main import run_index_job
from ingestion.parser.errors import ParseFailed


class FakeRepo:
    def __init__(self, ctx: JobContext):
        self._ctx = ctx
        self.stages: list[tuple[str, float]] = []
        self.completed = False
        self.failed: dict | None = None
        self.activated: tuple[str, str] | None = None

    def load_job(self, index_job_id):
        return self._ctx

    def mark_running(self, index_job_id):
        pass

    def set_stage(self, index_job_id, stage, progress):
        self.stages.append((stage, progress))

    def set_counts(self, index_job_id, *, chunk_count, vector_count):
        self.counts = (chunk_count, vector_count)

    def mark_completed(self, index_job_id):
        self.completed = True

    def mark_failed(self, index_job_id, *, stage, error):
        self.failed = {"stage": stage, "error": error}

    def mark_cancelled(self, index_job_id, *, reason):
        self.cancelled = reason

    def activate_version(self, document_id, version_id):
        self.activated = (document_id, version_id)


class FakeQdrant:
    def __init__(self):
        self.points = []

    def upsert(self, collection_name, points, wait=True):
        self.points.extend(points)

    def set_payload(self, **kwargs):
        pass

    def count(self, collection_name, count_filter, exact=True):
        class R:
            count = len(self.points)

        R.count = len(self.points)
        return R

    def query_points(self, collection_name, query, query_filter, limit):
        class R:
            points = [object()]

        return R


class FakeEmbedder:
    def embed(self, texts, on_progress=None):
        if on_progress is not None:
            on_progress(len(texts), len(texts))
        return [[0.1] * 4 for _ in texts]


def test_pipeline_runs_end_to_end(tmp_path):
    f = tmp_path / "doc.txt"
    f.write_text("본문 문장 하나. 두 번째 문장." * 20, encoding="utf-8")
    ctx = JobContext(
        index_job_id="job-1",
        document_version_id="ver-1",
        document_id="doc-1",
        version=1,
        file_path=str(f),
        title="테스트 문서",
        category="정책",
        allowed_channel_ids=["ch-a"],
    )
    repo = FakeRepo(ctx)
    qdrant = FakeQdrant()
    settings = Settings(qdrant_collection="rag_chunks_v1")

    n = run_index_job(
        "job-1",
        repo=repo,
        qdrant_client=qdrant,
        embedder=FakeEmbedder(),
        settings=settings,
    )
    assert n > 0
    assert repo.completed is True
    assert repo.failed is None
    assert repo.activated == ("doc-1", "ver-1")
    stages = [s for s, _ in repo.stages]
    assert "PARSING" in stages and "EMBEDDING" in stages and "VALIDATING" in stages


def test_pipeline_marks_failed_on_parse_error(tmp_path):
    f = tmp_path / "bad.xyz"
    f.write_text("x", encoding="utf-8")
    ctx = JobContext(
        index_job_id="job-2",
        document_version_id="ver-2",
        document_id="doc-2",
        version=1,
        file_path=str(f),
        title="깨진 문서",
    )
    repo = FakeRepo(ctx)
    settings = Settings()

    with contextlib.suppress(ParseFailed):
        run_index_job(
            "job-2",
            repo=repo,
            qdrant_client=FakeQdrant(),
            embedder=FakeEmbedder(),
            settings=settings,
        )
    assert repo.completed is False
    assert repo.failed is not None
    assert repo.failed["stage"] == "PARSING"


def test_fr_doc_008_job_for_inactive_or_deleted_document_is_cancelled(tmp_path):
    """비활성/삭제 후 실행된 대기 Job 은 아무것도 쓰지 않는다 — upsert(is_active=true)·activate_version 이
    문서를 되살리지 않게 (admin-api 비활성화/삭제와 짝)."""
    f = tmp_path / "doc.txt"
    f.write_text("본문 문장 하나. 두 번째 문장." * 20, encoding="utf-8")
    for status in ("INACTIVE", "DELETED"):
        ctx = JobContext(
            index_job_id="job-1",
            document_version_id="ver-1",
            document_id="doc-1",
            version=1,
            file_path=str(f),
            title="t",
            document_status=status,
        )
        repo, qdrant = FakeRepo(ctx), FakeQdrant()
        n = run_index_job(
            "job-1",
            repo=repo,
            qdrant_client=qdrant,
            embedder=FakeEmbedder(),
            settings=Settings(),
        )
        assert n == 0
        assert repo.cancelled == f"CANCELLED: document {status}"
        assert qdrant.points == []
        assert repo.activated is None and repo.completed is False and repo.stages == []


def test_fr_idx_005_embedding_progress_is_reported_between_batches():
    """긴 EMBEDDING 단계가 0.45 에 멈춰 보이지 않게 — 간격마다 progress 갱신, 마지막 batch 는 항상 기록."""
    from ingestion.main import _embedding_progress

    ctx = JobContext(
        index_job_id="job-p",
        document_version_id="ver-p",
        document_id="doc-p",
        version=1,
        file_path="x.txt",
        title="t",
    )
    repo = FakeRepo(ctx)
    now = [0.0]
    report = _embedding_progress(repo, "job-p", clock=lambda: now[0])

    for done, t in ((8, 5.0), (16, 12.0), (24, 15.0), (32, 30.0), (40, 31.0)):
        now[0] = t
        report(done, 40)

    # 5s(간격 미달)·15s(직전 기록 후 3s) 는 건너뛰고, 12s·30s 와 마지막(완료) 은 기록
    assert [p for _, p in repo.stages] == [0.55, 0.65, 0.7]
    assert {s for s, _ in repo.stages} == {"EMBEDDING"}
