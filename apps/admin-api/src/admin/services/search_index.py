"""검색 색인(Qdrant) 갱신 — 문서 비활성화/삭제를 검색에서 즉시 제외 (FR-DOC-008, TDD §7.5).

rag-api 는 Qdrant payload(`is_active`, `allowed_channel_ids`)만으로 검색 범위를 정하고 DB 문서 상태는 보지 않는다.
따라서 documents.status 만 바꾸면 비활성/삭제 문서가 계속 인용된다 → 해당 문서의 모든 point 를
`is_active=false` 로 바꾼 뒤에 DB 상태를 커밋한다(실패 시 503, DB 불변 — 화면과 실제가 어긋나지 않게).
재활성화는 재색인으로 한다(현재 ACL·버전으로 payload 를 다시 쓰므로 상태가 섞이지 않는다).
"""

from __future__ import annotations

from functools import lru_cache
from typing import Protocol

from rag_observability import get_logger

from admin.core.config import get_settings

log = get_logger("admin.search_index")


class SearchIndexError(RuntimeError):
    """Qdrant 갱신 실패. 호출자는 503 으로 응답하고 DB 상태를 바꾸지 않는다."""


class SearchIndex(Protocol):
    def deactivate_document(self, document_id: str) -> None:
        """document_id 의 모든 point(전 버전)를 is_active=false 로."""
        ...


class QdrantSearchIndex:
    def __init__(self, url: str, collection: str, timeout: float) -> None:
        self._url = url
        self._collection = collection
        self._timeout = timeout

    def deactivate_document(self, document_id: str) -> None:
        # lazy import — 테스트는 fake 를 주입하므로 qdrant_client 를 로드하지 않는다
        from qdrant_client import QdrantClient, models  # noqa: PLC0415

        try:
            client = QdrantClient(url=self._url, timeout=int(self._timeout))
            try:
                client.set_payload(
                    collection_name=self._collection,
                    payload={"is_active": False},
                    points=models.Filter(
                        must=[
                            models.FieldCondition(
                                key="document_id", match=models.MatchValue(value=document_id)
                            )
                        ]
                    ),
                    wait=True,
                )
            finally:
                client.close()
        except Exception as exc:  # noqa: BLE001 — 원인은 로그, 호출자는 503
            log.error(
                "search_index.deactivate_failed",
                document_id=document_id,
                error=type(exc).__name__,
            )
            raise SearchIndexError(f"{type(exc).__name__}: {exc}"[:300]) from exc
        log.info("search_index.document_deactivated", document_id=document_id)


@lru_cache
def get_search_index() -> SearchIndex:
    s = get_settings()
    return QdrantSearchIndex(s.qdrant_url, s.qdrant_collection, s.qdrant_timeout)


def provide_search_index() -> SearchIndex:
    """FastAPI dependency — 테스트는 dependency_overrides 로 fake 를 주입한다."""
    return get_search_index()
