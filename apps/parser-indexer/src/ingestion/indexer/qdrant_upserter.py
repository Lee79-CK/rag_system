"""Qdrant 멱등 Upsert (docs/TDD.md §7.7 step 7, §6.1, FR-IDX-006).

point id = chunk_point_id(chunk_id) = UUIDv5(namespace, chunk_id) → 재실행 멱등.
payload = QdrantChunkPayload (§4.4).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from qdrant_client import models
from rag_common import chunk_point_id, sha256_hex
from rag_schemas import QdrantChunkPayload

from ingestion.chunker.chunker import Chunk


@dataclass
class DocMetadata:
    """문서/버전 메타데이터 + ACL (§7.7 step 5)."""

    document_id: str
    document_version_id: str
    source_file: str
    title: str
    category: str | None = None
    department: str | None = None
    security_level: str = "INTERNAL"
    language: str = "ko"
    allowed_channel_ids: list[str] = field(default_factory=list)
    allowed_groups: list[str] = field(default_factory=list)


def build_payload(chunk: Chunk, meta: DocMetadata) -> QdrantChunkPayload:
    """단일 chunk → QdrantChunkPayload (§4.4)."""
    return QdrantChunkPayload(
        document_id=meta.document_id,
        document_version_id=meta.document_version_id,
        chunk_id=chunk.chunk_id,
        title=chunk.title or meta.title,
        source_file=meta.source_file,
        page_start=chunk.page_start,
        page_end=chunk.page_end,
        section=chunk.section,
        chunk_index=chunk.chunk_index,
        language=meta.language,
        category=meta.category,
        department=meta.department,
        security_level=meta.security_level,
        allowed_groups=list(meta.allowed_groups),
        allowed_channel_ids=list(meta.allowed_channel_ids),
        content_hash=sha256_hex(chunk.text),
        is_active=True,
        text=chunk.text,
    )


def build_points(
    chunks: list[Chunk],
    vectors: list[list[float]],
    meta: DocMetadata,
) -> list[models.PointStruct]:
    """chunk + vector → Qdrant PointStruct 목록. id는 결정론적(chunk_point_id)."""
    if len(chunks) != len(vectors):
        raise ValueError(f"chunk/vector 개수 불일치: {len(chunks)} != {len(vectors)}")
    points: list[models.PointStruct] = []
    for chunk, vector in zip(chunks, vectors, strict=True):
        payload = build_payload(chunk, meta)
        points.append(
            models.PointStruct(
                id=chunk_point_id(chunk.chunk_id),
                vector=vector,
                payload=payload.model_dump(),
            )
        )
    return points


class QdrantUpserter:
    """멱등 Upsert 어댑터. 동일 chunk_id는 항상 동일 point id로 덮어쓴다."""

    def __init__(self, client: object, collection: str) -> None:
        self._client = client
        self._collection = collection

    def upsert(
        self,
        chunks: list[Chunk],
        vectors: list[list[float]],
        meta: DocMetadata,
        *,
        batch_size: int = 256,
    ) -> int:
        """points를 batch로 upsert하고 upsert된 point 수를 반환한다."""
        points = build_points(chunks, vectors, meta)
        for start in range(0, len(points), batch_size):
            batch = points[start : start + batch_size]
            self._client.upsert(collection_name=self._collection, points=batch, wait=True)
        return len(points)

    def deactivate_other_versions(self, document_id: str, keep_version_id: str) -> None:
        """구버전 point들의 is_active=false 처리 (§6.3 버전 전환)."""
        self._client.set_payload(
            collection_name=self._collection,
            payload={"is_active": False},
            points=models.Filter(
                must=[
                    models.FieldCondition(
                        key="document_id", match=models.MatchValue(value=document_id)
                    )
                ],
                must_not=[
                    models.FieldCondition(
                        key="document_version_id",
                        match=models.MatchValue(value=keep_version_id),
                    )
                ],
            ),
            wait=True,
        )

    def count_by_version(self, version_id: str) -> int:
        """version_id 필터로 point 수를 센다 (§7.7 step 8 검증용)."""
        result = self._client.count(
            collection_name=self._collection,
            count_filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="document_version_id",
                        match=models.MatchValue(value=version_id),
                    )
                ]
            ),
            exact=True,
        )
        return int(getattr(result, "count", result))
