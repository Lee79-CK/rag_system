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


# ---------------------------------------------------------------- 인용한 근거만 표시 (FR-CHAT-003 / FR-CHAT-004)
def test_fr_chat_003_referenced_indices_formats():
    from rag.domain.citation import referenced_indices

    assert referenced_indices("A [2, 5] B", 8) == [2, 5]
    assert referenced_indices("A [1][3] B [3]", 8) == [1, 3]
    assert referenced_indices("범위 [1-3] · [6~10]", 8) == [1, 2, 3, 6, 7, 8]
    # 연도·범위 밖 번호는 근거 번호가 아니다
    assert referenced_indices("[2025]년 실적 [9] [0]", 8) == []
    assert referenced_indices("번호 없는 답변", 8) == []


def test_fr_chat_003_build_citations_keeps_only_cited_with_original_ref():
    chunks = [
        ScoredChunk(payload=_payload(i, f"본문{i}"), vector_score=0.9, rerank_score=0.9)
        for i in range(1, 6)
    ]
    cites = build_citations(chunks, [2, 5])
    assert [c.chunk_id for c in cites] == ["v1-00002", "v1-00005"]
    assert [c.ref for c in cites] == [2, 5]  # 본문 [5] ↔ 표 #5
    assert build_citations(chunks, []) == []
    assert [c.ref for c in build_citations(chunks)] == [1, 2, 3, 4, 5]  # refs 생략 = 전체


def test_fr_chat_004_no_evidence_answer_detection():
    from rag.domain.guardrail import is_no_evidence_answer

    assert is_no_evidence_answer("제공된 문서에서 관련 근거를 찾지 못했습니다.")
    assert is_no_evidence_answer(
        '@홍길동 제공된 문서에서 "생각보다 많군요"라는 표현에 대한 구체적인 근거나 맥락을 찾지 못했습니다.'
    )
    assert is_no_evidence_answer("해당 정보는 문서에 포함되어 있지 않습니다.")
    assert not is_no_evidence_answer("2020년 콘텐츠산업 사업체 수는 99,551개입니다.")


async def _run_with_answer(answer: str, n_chunks: int = 4):
    from rag.domain.pipeline import PipelineConfig, RagPipeline
    from rag.domain.ports import LLMStreamEvent

    class Emb:
        async def embed(self, texts):
            return [[0.0] * 4 for _ in texts]

    class Ret:
        async def search(self, v, f, k):
            return [RetrievedChunk(payload=_payload(i), score=0.9) for i in range(1, n_chunks + 1)]

    class Rr:
        async def rerank(self, q, docs, n):
            return [(i, 0.9 - i * 0.01) for i in range(len(docs))]

    class LLM:
        async def complete(self, *a, **k):
            raise AssertionError

        async def stream(self, messages, *, max_tokens, temperature):
            yield LLMStreamEvent(delta=answer)

    async def on_delta(d: str) -> None:
        pass

    pipe = RagPipeline(
        embedding=Emb(),
        retrieval=Ret(),
        reranker=Rr(),
        llm=LLM(),
        token_counter=HeuristicTokenCounter(),
        config=PipelineConfig(),
    )
    return await pipe.run(question="q", binding=_binding(), on_delta=on_delta)


async def test_fr_chat_003_pipeline_cites_only_referenced_chunks():
    out = await _run_with_answer(
        "연간 합계는 명시되어 있지 않습니다. 다만 분기별 매출은 다음과 같습니다 [2, 4]."
    )
    assert out.insufficient_evidence is False  # 번호를 인용한 부분 답변은 근거 부족이 아니다
    assert [c.ref for c in out.citations] == [2, 4]
    assert out.usage["citation_refs"] == 2


async def test_fr_chat_004_pipeline_llm_no_evidence_answer_has_no_citations():
    text = "제공된 문서에서 관련 근거를 찾지 못했습니다."
    out = await _run_with_answer(text)
    assert out.insufficient_evidence is True
    assert out.citations == []
    assert out.answer == text  # 스트리밍된 본문 그대로
    assert out.usage["llm_insufficient"] == 1


async def test_fr_chat_003_pipeline_uncited_answer_hides_table():
    out = await _run_with_answer("일반적인 안내 문장입니다.")
    assert out.insufficient_evidence is False
    assert out.citations == []
    assert out.usage["citation_refs"] == 0


def test_fr_chat_014_direct_messages_native_roles():
    from rag.domain.prompt import DIRECT_SYSTEM_PROMPT, build_direct_messages

    msgs = build_direct_messages(
        question="번역해줘",
        history=[("user", "질문"), ("assistant", "답변 [1]"), ("system", "무시")],
    )
    assert msgs[0] == {"role": "system", "content": DIRECT_SYSTEM_PROMPT}
    assert [(m["role"], m["content"]) for m in msgs[1:]] == [
        ("user", "질문"),
        ("assistant", "답변 [1]"),
        ("user", "번역해줘"),
    ]
