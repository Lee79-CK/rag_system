"""Qdrant collection 초기화 테스트 (docs/TDD.md §6.1, §6.2)."""

from __future__ import annotations

from ingestion.tools.qdrant_init import PAYLOAD_INDEXES, init_collection
from qdrant_client import models


class FakeQdrantClient:
    def __init__(self, exists: bool = False):
        self._exists = exists
        self.created_collections = []
        self.payload_indexes = []

    def collection_exists(self, name):
        return self._exists

    def create_collection(self, collection_name, vectors_config):
        self.created_collections.append((collection_name, vectors_config))

    def create_payload_index(self, collection_name, field_name, field_schema):
        self.payload_indexes.append((field_name, field_schema))


def test_qdrant_init_creates_collection_and_indexes():
    client = FakeQdrantClient(exists=False)
    init_collection(client, "rag_chunks_v1", vector_dim=1024)

    # collection 1회 생성, dim=1024, Cosine
    assert len(client.created_collections) == 1
    name, cfg = client.created_collections[0]
    assert name == "rag_chunks_v1"
    assert cfg.size == 1024
    assert cfg.distance == models.Distance.COSINE

    # §6.2 payload index 7종
    assert len(client.payload_indexes) == 7
    fields = [f for f, _ in client.payload_indexes]
    assert fields == [f for f, _ in PAYLOAD_INDEXES]
    assert "is_active" in fields
    assert "allowed_channel_ids" in fields


def test_qdrant_init_idempotent_when_exists():
    client = FakeQdrantClient(exists=True)
    init_collection(client, "rag_chunks_v1", vector_dim=1024)
    # 이미 존재하면 collection 재생성하지 않는다
    assert client.created_collections == []
    # payload index는 멱등하게 재요청 (이미 존재하면 무시)
    assert len(client.payload_indexes) == 7
