"""QdrantClient 팩토리 — 명시적 timeout 필수 (docs/TDD.md §3.2)."""

from __future__ import annotations

from qdrant_client import QdrantClient


def create_qdrant_client(url: str, *, timeout: float = 30.0) -> QdrantClient:
    """URL + 명시 timeout으로 QdrantClient를 생성한다."""
    return QdrantClient(url=url, timeout=int(timeout))
