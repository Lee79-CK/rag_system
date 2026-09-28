"""Channel 격리 테스트 공용 fixture/fake (§13.2, PRD §25.4).

CH-001~010은 Channel 간 문서·대화가 절대 섞이지 않음을 보증하는 배포 차단 Gate다.
여기서는 인프라 없이 실행 가능한 hermetic 검증(build_filter + conversation scope +
LLM payload capture)을 제공하고, 실제 Qdrant 검증은 test_ch_qdrant.py(testcontainers)에 둔다.
"""

from __future__ import annotations

import pytest
from rag.domain.ports import LLMResult, LLMStreamEvent, RetrievedChunk
from rag_schemas import ChannelBinding, ChannelMode, ChatRequest, KnowledgeScope, QdrantChunkPayload


def make_binding(
    channel_id: str,
    *,
    enabled: bool = True,
    categories: list[str] | None = None,
    departments: list[str] | None = None,
    security_levels: list[str] | None = None,
) -> ChannelBinding:
    return ChannelBinding(
        id=f"binding-{channel_id}",
        channel_id=channel_id,
        channel_name=f"ch-{channel_id}",
        mode=ChannelMode.DEDICATED_CHANNEL,
        enabled=enabled,
        knowledge_scope=KnowledgeScope(
            categories=categories or [],
            departments=departments or [],
            security_levels=security_levels or ["INTERNAL"],
        ),
        feedback_enabled=True,
    )


def make_payload(chunk_id: str, channel_ids: list[str], text: str, **meta) -> QdrantChunkPayload:
    return QdrantChunkPayload(
        document_id=meta.get("document_id", "doc"),
        document_version_id="v1",
        chunk_id=chunk_id,
        title=meta.get("title", "문서"),
        source_file="/x.pdf",
        page_start=1,
        chunk_index=0,
        category=meta.get("category"),
        department=meta.get("department"),
        security_level=meta.get("security_level", "INTERNAL"),
        allowed_channel_ids=channel_ids,
        content_hash="sha256:x",
        is_active=meta.get("is_active", True),
        text=text,
    )


def make_request(channel_id: str, message: str, *, user_name: str = "user") -> ChatRequest:
    return ChatRequest(
        source="web",
        channel_id=channel_id,
        user_id="u1",
        user_name=user_name,
        post_id=f"post-{channel_id}",
        root_id=None,
        bot_post_id=f"bot-post-{channel_id}",
        message=message,
        trace_id="t",
    )


class InMemoryQdrant:
    """build_filter(qdrant Filter)를 실제로 평가하는 최소 in-memory 검색기.

    Qdrant payload filter 의미(must + MatchValue/MatchAny)를 재현하여 격리 규칙을 검증한다.
    """

    def __init__(self, points: list[QdrantChunkPayload]) -> None:
        self._points = points

    async def search(self, query_vector, qdrant_filter, top_k):
        results: list[RetrievedChunk] = []
        for p in self._points:
            if self._matches(p, qdrant_filter):
                results.append(RetrievedChunk(payload=p, score=1.0))
        return results[:top_k]

    @staticmethod
    def _matches(payload: QdrantChunkPayload, qdrant_filter) -> bool:
        for cond in qdrant_filter.must:
            key = cond.key
            value = getattr(payload, key, None)
            match = cond.match
            wanted = getattr(match, "value", None)
            any_of = getattr(match, "any", None)
            if wanted is not None:
                if value != wanted:
                    return False
            elif any_of is not None:
                # allowed_channel_ids 처럼 list인 payload는 교집합, scalar는 포함 검사
                if isinstance(value, list):
                    if not set(value) & set(any_of):
                        return False
                elif value not in any_of:
                    return False
        return True


class CapturingLLM:
    """LLM 요청 payload를 캡처해 다른 Channel 문자열 유입 여부를 검사한다 (CH-002/003)."""

    def __init__(self) -> None:
        self.messages: list[dict] = []

    async def complete(self, messages, *, max_tokens, temperature):
        self.messages = messages
        return LLMResult(text="답변입니다. [1]", usage={})

    async def stream(self, messages, *, max_tokens, temperature):
        """Worker 운영 경로(스트리밍) — 동일하게 payload 를 캡처한다."""
        self.messages = messages
        yield LLMStreamEvent(delta="답변입니다. [1]")


class FakeEmbedding:
    async def embed(self, texts):
        return [[0.1] * 1024 for _ in texts]


class PassthroughRerank:
    async def rerank(self, query, documents, top_n):
        return [(i, 1.0 - i * 0.01) for i in range(min(top_n, len(documents)))]


@pytest.fixture
def embedding():
    return FakeEmbedding()


@pytest.fixture
def reranker():
    return PassthroughRerank()
