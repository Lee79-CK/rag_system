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
    def embed(self, texts):
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
