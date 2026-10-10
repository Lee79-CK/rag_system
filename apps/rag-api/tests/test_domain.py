"""rag domain 단위 테스트 — filter/budget/guardrail/prompt/citation."""

from __future__ import annotations

from rag.domain.citation import build_citations
from rag.domain.context import BudgetConfig, assemble_context
from rag.domain.guardrail import (
    is_insufficient_after_rerank,
    is_insufficient_after_search,
)
from rag.domain.ports import RetrievedChunk, ScoredChunk
from rag.domain.prompt import SYSTEM_PROMPT, build_messages
from rag.domain.retrieval import build_filter
from rag.domain.tokens import HeuristicTokenCounter
from rag_schemas import ChannelBinding, ChannelMode, KnowledgeScope, QdrantChunkPayload


def _binding(**scope) -> ChannelBinding:
    return ChannelBinding(
        id="b1",
        channel_id="channel-001",
        channel_name="rag-cloud-ops",
        mode=ChannelMode.DEDICATED_CHANNEL,
        enabled=True,
        knowledge_scope=KnowledgeScope(**scope),
    )


def _payload(idx: int, text: str = "본문") -> QdrantChunkPayload:
    return QdrantChunkPayload(
        document_id=f"d{idx}",
        document_version_id="v1",
        chunk_id=f"v1-{idx:05d}",
        title=f"문서{idx}",
        source_file="/x.pdf",
        page_start=idx,
        chunk_index=idx,
        content_hash="sha256:x",
        text=text,
    )


def test_build_filter_always_includes_active_and_channel():
    f = build_filter(_binding())
    keys = [c.key for c in f.must]  # type: ignore[union-attr]
    assert "is_active" in keys
    assert "allowed_channel_ids" in keys


def test_build_filter_adds_scope_conditions():
    f = build_filter(
        _binding(
            categories=["운영매뉴얼"], departments=["Cloud운영팀"], security_levels=["INTERNAL"]
        )
    )
    keys = [c.key for c in f.must]  # type: ignore[union-attr]
    assert "category" in keys
    assert "department" in keys
    assert "security_level" in keys


def test_fr_rag_004_unscoped_binding_does_not_filter_security_level():
    """지식 범위 미지정 = 채널 ACL(is_active + allowed_channel_ids)만. PUBLIC 문서도 검색돼야 한다."""
    f = build_filter(_binding())
    keys = [c.key for c in f.must]  # type: ignore[union-attr]
    assert keys == ["is_active", "allowed_channel_ids"]


def test_guardrail_search_zero_and_threshold():
    assert is_insufficient_after_search([], 0.0) is True
    chunks = [RetrievedChunk(payload=_payload(1), score=0.2)]
    assert is_insufficient_after_search(chunks, 0.5) is True
    assert is_insufficient_after_search(chunks, 0.1) is False


def test_guardrail_rerank_threshold():
    ranked = [ScoredChunk(payload=_payload(1), vector_score=0.9, rerank_score=0.1)]
    assert is_insufficient_after_rerank(ranked, 0.5) is True
    assert is_insufficient_after_rerank(ranked, 0.05) is False


def test_token_budget_guarantees_at_least_one_chunk():
    counter = HeuristicTokenCounter()
    huge = "가" * 100000  # budget을 초과하는 거대한 chunk
    reranked = [ScoredChunk(payload=_payload(1, huge), vector_score=0.9, rerank_score=0.9)]
    ctx = assemble_context(
        counter=counter,
        system_prompt=SYSTEM_PROMPT,
        question="질문",
        history=[],
        reranked=reranked,
        config=BudgetConfig(max_context_tokens=1024),
    )
    assert len(ctx.selected_chunks) == 1  # 최소 1개 보장


def test_token_budget_trims_old_history():
    counter = HeuristicTokenCounter()
    long_history = [("user", "옛날 대화 " * 200), ("assistant", "옛날 답변 " * 200)]
    reranked = [ScoredChunk(payload=_payload(1, "짧은근거"), vector_score=0.9, rerank_score=0.9)]
    ctx = assemble_context(
        counter=counter,
        system_prompt=SYSTEM_PROMPT,
        question="질문",
        history=long_history,
        reranked=reranked,
        config=BudgetConfig(max_context_tokens=2048),
    )
    assert ctx.trimmed_history_turns >= 1


def test_prompt_contains_rules_and_evidence():
    chunks = [
        ScoredChunk(payload=_payload(1, "장애 등급 절차"), vector_score=0.9, rerank_score=0.9)
    ]
    messages = build_messages(question="장애 절차?", chunks=chunks, history=[("user", "안녕")])
    assert messages[0]["role"] == "system"
    assert "근거 문서" in messages[0]["content"]
    user = messages[1]["content"]
    assert "[대화 이력]" in user
    assert "[근거 문서]" in user
    assert "[질문]" in user


def test_citation_excerpt_truncated_to_200():
    chunks = [ScoredChunk(payload=_payload(1, "본" * 500), vector_score=0.9, rerank_score=0.88)]
    cites = build_citations(chunks)
    assert len(cites) == 1
    assert len(cites[0].excerpt) <= 200
    assert cites[0].score == 0.88
    assert cites[0].chunk_id == "v1-00001"


# ---------------------------------------------------------------- streaming (ADR-001 개정)
async def test_pipeline_streaming_delivers_deltas_in_order():
    from rag.domain.pipeline import PipelineConfig, RagPipeline
    from rag.domain.ports import LLMStreamEvent, RetrievedChunk
    from rag.domain.tokens import HeuristicTokenCounter

    class Emb:
        async def embed(self, texts):
            return [[0.0] * 4 for _ in texts]

    class Ret:
        async def search(self, v, f, k):
            return [RetrievedChunk(payload=_payload(1), score=0.9)]

    class Rr:
        async def rerank(self, q, docs, n):
            return [(0, 0.9)]

    class StreamLLM:
        async def complete(self, *a, **k):
            raise AssertionError("streaming path must not call complete()")

        async def stream(self, messages, *, max_tokens, temperature):
            for t in ["가", "나", "다"]:
                yield LLMStreamEvent(delta=t)
            yield LLMStreamEvent(usage={"completion_tokens": 3})

    got: list[str] = []

    async def on_delta(d: str) -> None:
        got.append(d)

    pipe = RagPipeline(
        embedding=Emb(),
        retrieval=Ret(),
        reranker=Rr(),
        llm=StreamLLM(),
        token_counter=HeuristicTokenCounter(),
        config=PipelineConfig(),
    )
    out = await pipe.run(question="q", binding=_binding(), on_delta=on_delta)
    assert got == ["가", "나", "다"]
    assert out.answer == "가나다"
    assert out.usage["completion_tokens"] == 3
    assert "llm_first_token_ms" in out.usage


# ---------------------------------------------------------------- reranker 장애 대체 (FR-RAG-006 Graceful degradation)
async def test_fr_rag_006_rerank_failure_falls_back_to_vector_order():
    """reranker timeout/5xx 는 답변 실패가 아니라 벡터 점수 순서 상위 top_n 으로 대체 — 근거 답변 유지."""
    from rag.domain.pipeline import PipelineConfig, RagPipeline
    from rag.domain.ports import LLMStreamEvent
    from rag.domain.tokens import HeuristicTokenCounter

    class Emb:
        async def embed(self, texts):
            return [[0.0] * 4 for _ in texts]

    class Ret:
        async def search(self, v, f, k):
            return [
                RetrievedChunk(payload=_payload(1, "약한 근거"), score=0.3),
                RetrievedChunk(payload=_payload(2, "강한 근거"), score=0.9),
                RetrievedChunk(payload=_payload(3, "중간 근거"), score=0.6),
            ]

    class TimeoutRr:
        async def rerank(self, q, docs, n):
            raise TimeoutError("reranker ReadTimeout")

    seen: list[list[dict]] = []

    class LLM:
        async def complete(self, *a, **k):
            raise AssertionError

        async def stream(self, messages, *, max_tokens, temperature):
            seen.append(messages)
            yield LLMStreamEvent(delta="답변 [1]")

    async def on_delta(d: str) -> None:
        pass

    pipe = RagPipeline(
        embedding=Emb(),
        retrieval=Ret(),
        reranker=TimeoutRr(),
        llm=LLM(),
        token_counter=HeuristicTokenCounter(),
        # 임계값이 있어도 대체 시에는 rerank 임계값(점수 척도가 다름)으로 '근거 없음' 처리하지 않는다
        config=PipelineConfig(rerank_top_n=2, rerank_score_threshold=0.95),
    )
    out = await pipe.run(question="q", binding=_binding(), on_delta=on_delta)
    assert out.insufficient_evidence is False
    assert out.usage["rerank_fallback"] == 1
    assert [c.payload.chunk_id for c in out.selected_chunks] == ["v1-00002", "v1-00003"]
    assert out.answer == "답변 [1]" and seen  # LLM 까지 호출됨


def test_fr_chat_009_worker_error_text_names_exception_and_url():
    """httpx.ReadTimeout 은 str(exc) 가 비어 chat_jobs.error 가 빈칸이 됐다 — 종류·대상 URL 을 남긴다."""
    import httpx
    from rag.worker.chat_worker import _error_text

    req = httpx.Request("POST", "http://reranker-api.rag-ai:8005/internal/v1/rerank")
    text = _error_text(httpx.ReadTimeout("", request=req))
    assert text.startswith("ReadTimeout: ")
    assert "reranker-api.rag-ai:8005/internal/v1/rerank" in text
    assert _error_text(ValueError("bad")) == "ValueError: bad"
