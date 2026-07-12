"""Qdrant collection 초기화 — 멱등 (docs/TDD.md §6.1, §6.2).

실행: `python -m ingestion.tools.qdrant_init`

- Collection `rag_chunks_v1` 없으면 생성 (Dense dim=1024, Distance.COSINE).
- §6.2의 7개 payload index 생성. 이미 존재하면 무시(멱등).
"""

from __future__ import annotations

from qdrant_client import models
from rag_observability import configure_logging, get_logger

from ingestion.core.config import get_settings
from ingestion.indexer.qdrant_client_factory import create_qdrant_client

logger = get_logger(__name__)

# §6.2 — 검색 p95 ≤ 1초 달성을 위한 payload index 7종.
PAYLOAD_INDEXES: list[tuple[str, models.PayloadSchemaType]] = [
    ("is_active", models.PayloadSchemaType.BOOL),
    ("document_id", models.PayloadSchemaType.KEYWORD),
    ("document_version_id", models.PayloadSchemaType.KEYWORD),
    ("allowed_channel_ids", models.PayloadSchemaType.KEYWORD),
    ("category", models.PayloadSchemaType.KEYWORD),
    ("department", models.PayloadSchemaType.KEYWORD),
    ("security_level", models.PayloadSchemaType.KEYWORD),
]


def init_collection(
    client: object,
    collection: str,
    *,
    vector_dim: int = 1024,
) -> None:
    """collection + payload index를 멱등하게 생성한다."""
    if not client.collection_exists(collection):
        client.create_collection(
            collection_name=collection,
            vectors_config=models.VectorParams(size=vector_dim, distance=models.Distance.COSINE),
        )
        logger.info("collection_created", collection=collection, dim=vector_dim)
    else:
        logger.info("collection_exists", collection=collection)

    for field_name, schema in PAYLOAD_INDEXES:
        try:
            client.create_payload_index(
                collection_name=collection,
                field_name=field_name,
                field_schema=schema,
            )
            logger.info("payload_index_created", field=field_name)
        except Exception as exc:  # noqa: BLE001
            # 이미 존재하는 index는 무시(멱등). 그 외는 로깅만 하고 계속.
            logger.info("payload_index_skipped", field=field_name, reason=str(exc))


def main() -> None:
    settings = get_settings()
    configure_logging("parser-indexer")
    client = create_qdrant_client(settings.qdrant_url, timeout=settings.qdrant_timeout)
    try:
        init_collection(client, settings.qdrant_collection, vector_dim=settings.vector_dim)
    finally:
        client.close()


if __name__ == "__main__":
    main()
