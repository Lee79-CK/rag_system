"""색인 후 검증 (docs/TDD.md §7.7 step 8, FR-IDX-007).

- PG chunk_count == Qdrant count(filter=version_id)
- 샘플 3개 chunk 검색 smoke test
실패 시 IndexFailed.
"""

from __future__ import annotations

from qdrant_client import models

from ingestion.parser.errors import IndexFailed


def validate_counts(pg_chunk_count: int, qdrant_count: int) -> None:
    """PG chunk_count == Qdrant point count 검증."""
    if pg_chunk_count != qdrant_count:
        raise IndexFailed(
            f"chunk 수 불일치: PG={pg_chunk_count}, Qdrant={qdrant_count}",
            code="COUNT_MISMATCH",
        )


def smoke_test(
    client: object,
    collection: str,
    version_id: str,
    sample_vectors: list[list[float]],
) -> None:
    """샘플 벡터로 검색이 동작하고 결과가 반환되는지 확인한다 (최대 3개)."""
    samples = sample_vectors[:3]
    if not samples:
        return
    version_filter = models.Filter(
        must=[
            models.FieldCondition(
                key="document_version_id", match=models.MatchValue(value=version_id)
            )
        ]
    )
    for i, vector in enumerate(samples):
        results = client.query_points(
            collection_name=collection,
            query=vector,
            query_filter=version_filter,
            limit=1,
        )
        points = getattr(results, "points", results)
        if not points:
            raise IndexFailed(
                f"smoke test 실패: 샘플 {i}에 대한 검색 결과 0건",
                code="SMOKE_TEST_EMPTY",
            )


def validate_index(
    client: object,
    collection: str,
    version_id: str,
    *,
    pg_chunk_count: int,
    qdrant_count: int,
    sample_vectors: list[list[float]],
) -> None:
    """count 검증 + smoke test를 함께 수행한다."""
    validate_counts(pg_chunk_count, qdrant_count)
    smoke_test(client, collection, version_id, sample_vectors)
