"""식별자 생성 유틸.

- request_id: 수신 시 생성 (§3.2)
- trace_id: 파이프라인 전파 (§3.2)
- chunk_point_id: Qdrant Point ID = UUIDv5(namespace, chunk_id) — 멱등 Upsert (§6.1, FR-IDX-006)
"""

from __future__ import annotations

import uuid

# 고정 namespace — chunk_id → point id 매핑이 재실행 간 안정적이어야 한다 (멱등성).
_QDRANT_NAMESPACE = uuid.UUID("6f9b1e2a-0c3d-5e4f-8a7b-9c0d1e2f3a4b")


def new_request_id() -> str:
    return f"req-{uuid.uuid4().hex}"


def new_trace_id() -> str:
    return f"trace-{uuid.uuid4().hex}"


def chunk_point_id(chunk_id: str) -> str:
    """chunk_id → 결정론적 UUIDv5 문자열. 동일 chunk_id는 항상 동일 point id."""
    return str(uuid.uuid5(_QDRANT_NAMESPACE, chunk_id))
