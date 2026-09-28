"""CH-001 실제 Qdrant 검증 (testcontainers) — §13.2 "mock이 아닌 실제 Qdrant".

Docker 미기동/testcontainers 미설치 환경에서는 skip한다 (로컬). CI에서는 배포 Gate로 실행.
build_filter의 payload filter 의미가 실제 Qdrant에서도 Channel 격리를 보장하는지 확인한다.
"""

from __future__ import annotations

import uuid

import pytest

testcontainers = pytest.importorskip("testcontainers.core.container")

from conftest import make_binding  # noqa: E402
from qdrant_client import QdrantClient  # noqa: E402
from qdrant_client import models as qm  # noqa: E402
from rag.domain.retrieval import build_filter  # noqa: E402
from rag_schemas import QdrantChunkPayload  # noqa: E402

COLLECTION = "rag_chunks_v1"
CHANNEL_A = "channel-A"
CHANNEL_B = "channel-B"


def _docker_available() -> bool:
    try:
        import docker  # noqa: F401

        client = docker.from_env()
        client.ping()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _docker_available(), reason="Docker 미기동 — testcontainers 실행 불가"
)


@pytest.fixture(scope="module")
def qdrant_url():
    from testcontainers.core.container import DockerContainer
    from testcontainers.core.waiting_utils import wait_for_logs

    container = (
        DockerContainer("qdrant/qdrant:v1.12.1").with_exposed_ports(6333).with_exposed_ports(6334)
    )
    container.start()
    wait_for_logs(container, "Actix runtime found", timeout=60)
    host = container.get_container_host_ip()
    port = container.get_exposed_port(6333)
    yield f"http://{host}:{port}"
    container.stop()


def _seed(client: QdrantClient) -> None:
    client.recreate_collection(
        COLLECTION, vectors_config=qm.VectorParams(size=1024, distance=qm.Distance.COSINE)
    )
    for field, ftype in [
        ("is_active", "bool"),
        ("allowed_channel_ids", "keyword"),
        ("category", "keyword"),
        ("department", "keyword"),
        ("security_level", "keyword"),
        ("document_id", "keyword"),
        ("document_version_id", "keyword"),
    ]:
        client.create_payload_index(COLLECTION, field, ftype)

    def payload(chunk_id, channels, text):
        return QdrantChunkPayload(
            document_id=chunk_id,
            document_version_id="v1",
            chunk_id=chunk_id,
            title=chunk_id,
            source_file="/x",
            chunk_index=0,
            allowed_channel_ids=channels,
            content_hash="sha256:x",
            text=text,
        ).model_dump()

    points = [
        qm.PointStruct(
            id=str(uuid.uuid4()), vector=[0.1] * 1024, payload=payload("x", [CHANNEL_A], "A doc")
        ),
        qm.PointStruct(
            id=str(uuid.uuid4()), vector=[0.1] * 1024, payload=payload("y", [CHANNEL_B], "B doc")
        ),
    ]
    client.upsert(COLLECTION, points=points)


def test_ch_001_real_qdrant_channel_filter(qdrant_url):
    client = QdrantClient(url=qdrant_url)
    _seed(client)

    # Channel B는 A 전용 문서 X를 절대 검색하지 못한다
    res_b = client.query_points(
        COLLECTION,
        query=[0.1] * 1024,
        query_filter=build_filter(make_binding(CHANNEL_B)),
        limit=10,
    ).points
    ids_b = {p.payload["chunk_id"] for p in res_b}
    assert "x" not in ids_b

    # Channel A는 자신의 문서만 본다
    res_a = client.query_points(
        COLLECTION,
        query=[0.1] * 1024,
        query_filter=build_filter(make_binding(CHANNEL_A)),
        limit=10,
    ).points
    ids_a = {p.payload["chunk_id"] for p in res_a}
    assert ids_a == {"x"}
