"""Qdrant Upsert 멱등성 테스트 (docs/TDD.md §6.1, FR-IDX-006)."""

from __future__ import annotations

from ingestion.chunker.chunker import Chunk
from ingestion.indexer.qdrant_upserter import DocMetadata, QdrantUpserter, build_points
from rag_common import chunk_point_id


class FakeQdrantClient:
    def __init__(self):
        self.upsert_calls = []

    def upsert(self, collection_name, points, wait=True):
        self.upsert_calls.append((collection_name, points))


def _chunks() -> list[Chunk]:
    return [
        Chunk(
            chunk_id="ver-1-00000",
            chunk_index=0,
            text="첫 청크",
            title="문서",
            section="A",
            page_start=1,
            page_end=1,
        ),
        Chunk(
            chunk_id="ver-1-00001",
            chunk_index=1,
            text="둘째 청크",
            title="문서",
            section="A",
            page_start=1,
            page_end=1,
        ),
    ]


def _meta() -> DocMetadata:
    return DocMetadata(
        document_id="doc-1",
        document_version_id="ver-1",
        source_file="a.pdf",
        title="문서",
        category="정책",
        department="인사",
        security_level="INTERNAL",
        allowed_channel_ids=["ch-a", "ch-b"],
    )


def test_fr_idx_006_qdrant_point_id_idempotent():
    chunks = _chunks()
    vectors = [[0.1] * 4, [0.2] * 4]

    # 동일 chunk_id → 동일 point id (재실행 간 안정)
    assert chunk_point_id("ver-1-00000") == chunk_point_id("ver-1-00000")

    client = FakeQdrantClient()
    upserter = QdrantUpserter(client, "rag_chunks_v1")

    n1 = upserter.upsert(chunks, vectors, _meta())
    n2 = upserter.upsert(chunks, vectors, _meta())
    assert n1 == n2 == 2

    # 두 번의 upsert에서 캡처된 point id가 chunk_point_id와 정확히 일치
    ids_run1 = [p.id for p in client.upsert_calls[0][1]]
    ids_run2 = [p.id for p in client.upsert_calls[1][1]]
    assert ids_run1 == ids_run2
    assert ids_run1 == [chunk_point_id("ver-1-00000"), chunk_point_id("ver-1-00001")]

    # payload가 QdrantChunkPayload 필드로 채워졌는지
    payload0 = client.upsert_calls[0][1][0].payload
    assert payload0["chunk_id"] == "ver-1-00000"
    assert payload0["allowed_channel_ids"] == ["ch-a", "ch-b"]
    assert payload0["is_active"] is True
    assert payload0["content_hash"].startswith("sha256:")
    assert payload0["category"] == "정책"


def test_build_points_uses_deterministic_ids():
    points = build_points(_chunks(), [[0.0] * 4, [0.0] * 4], _meta())
    assert points[0].id == chunk_point_id("ver-1-00000")
    assert points[1].id == chunk_point_id("ver-1-00001")
