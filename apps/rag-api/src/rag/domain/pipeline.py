"""RAG 파이프라인 오케스트레이션 (§7.2.1). 프레임워크/인프라 비종속.

포트(embed/search/rerank/llm)와 순수 도메인 로직만으로 RagCompletion 재료를 만든다.
대화 이력 로딩·메시지 영속화·Job 상태·게시는 Worker 계층이 담당한다 (도메인 순수성 유지).
"""

from __future__ import annotations

import dataclasses
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from rag_schemas import ChannelBinding, Citation

from rag.domain import guardrail
from rag.domain.citation import build_citations, referenced_indices
from rag.domain.context import BudgetConfig, assemble_context
from rag.domain.ports import (
    EmbeddingPort,
    LLMPort,
    RerankPort,
    RetrievalPort,
    RetrievedChunk,
    ScoredChunk,
)
from rag.domain.prompt import (
    DIRECT_SYSTEM_PROMPT,
    INSUFFICIENT_EVIDENCE_TEXT,
    SYSTEM_PROMPT,
    build_direct_messages,
    build_messages,
)
from rag.domain.retrieval import build_filter

DeltaCallback = Callable[[str], Awaitable[None]]


@dataclass(slots=True)
class PipelineConfig:
    vector_top_k: int = 30
    rerank_top_n: int = 8
    similarity_threshold: float = 0.0
    rerank_score_threshold: float = 0.0
    max_output_tokens: int = 1024
    temperature: float = 0.2
    budget: BudgetConfig = field(default_factory=BudgetConfig)


@dataclass(slots=True)
class PipelineOutput:
    answer: str
    citations: list[Citation]
    insufficient_evidence: bool
    usage: dict
    selected_chunks: list[ScoredChunk] = field(default_factory=list)


class RagPipeline:
    """§7.2.1 파이프라인. 포트는 생성자 주입 → 테스트에서 fake 교체 가능."""

    def __init__(
        self,
        *,
        embedding: EmbeddingPort,
        retrieval: RetrievalPort,
        reranker: RerankPort,
        llm: LLMPort,
        token_counter,
        config: PipelineConfig,
    ) -> None:
        self._embed = embedding
        self._retrieval = retrieval
        self._rerank = reranker
        self._llm = llm
        self._counter = token_counter
        self._cfg = config

    async def run(
        self,
        *,
        question: str,
        binding: ChannelBinding,
        history: list[tuple[str, str]] | None = None,
        on_delta: DeltaCallback | None = None,
    ) -> PipelineOutput:
        """on_delta 가 주어지면 LLM 을 스트리밍 호출하고 토큰 조각마다 콜백한다.

        근거 부족 시에는 LLM 을 호출하지 않으며 on_delta 도 호출하지 않는다
        (최종 본문은 Worker 가 답변 갱신 시 한 번에 반영).
        """
        history = history or []
        usage: dict[str, float | int] = {}

        # 5. Embedding
        t = time.perf_counter()
        vectors = await self._embed.embed([question])
        usage["embedding_ms"] = _ms(t)
        query_vector = vectors[0]

        # 6. Qdrant search — build_filter 강제 (§11 #4)
        t = time.perf_counter()
        qfilter = build_filter(binding)
        retrieved: list[RetrievedChunk] = await self._retrieval.search(
            query_vector, qfilter, self._cfg.vector_top_k
        )
        usage["search_ms"] = _ms(t)

        # 7. Threshold 판정 → 근거 부족이면 LLM 미호출 (§7.2.3)
        if guardrail.is_insufficient_after_search(retrieved, self._cfg.similarity_threshold):
            return _insufficient(usage)

        # 8. Re-rank (후보 → top_n). reranker 장애(timeout·5xx·연결 실패)는 답변 실패로 만들지 않고
        #    벡터 점수 순서 상위 top_n 으로 대체한다 — 품질은 다소 낮아도 사용자는 오류 대신 근거 답변을 받는다.
        #    대체 여부는 usage["rerank_fallback"] 로 호출자(worker/API)가 로그·지표로 남긴다.
        t = time.perf_counter()
        docs = [c.payload.text for c in retrieved]
        try:
            ranked = await self._rerank.rerank(question, docs, self._cfg.rerank_top_n)
        except Exception:  # noqa: BLE001 — 어떤 reranker 오류든 동일하게 대체
            ranked = None
        if ranked is None:
            usage["rerank_fallback"] = 1
            by_vector = sorted(retrieved, key=lambda c: c.score, reverse=True)
            reranked = [
                ScoredChunk(payload=c.payload, vector_score=c.score, rerank_score=c.score)
                for c in by_vector[: self._cfg.rerank_top_n]
            ]
        else:
            reranked = [
                ScoredChunk(
                    payload=retrieved[idx].payload,
                    vector_score=retrieved[idx].score,
                    rerank_score=score,
                )
                for idx, score in ranked
            ]
        usage["rerank_ms"] = _ms(t)

        # rerank 점수 임계값은 reranker 점수 척도 기준 — 대체 시(벡터 점수)는 검색 임계값(7단계)으로 이미 판정됨
        if not usage.get("rerank_fallback") and guardrail.is_insufficient_after_rerank(
            reranked, self._cfg.rerank_score_threshold
        ):
            return _insufficient(usage)

        # 9. Context 조립 (Token Budget)
        assembled = assemble_context(
            counter=self._counter,
            system_prompt=SYSTEM_PROMPT,
            question=question,
            history=history,
            reranked=reranked,
            config=self._cfg.budget,
        )
        usage["context_tokens"] = assembled.used_tokens
        usage["context_chunks"] = len(assembled.selected_chunks)

        # 10-11. Prompt 조립 + vLLM 생성
        messages = build_messages(
            question=question, chunks=assembled.selected_chunks, history=assembled.history
        )
        answer = await self._generate(messages, on_delta, usage)

        # 12. Citation 생성 — 답변이 인용한 근거 번호의 chunk 만. 인용이 없으면 근거 문서 표를 내지 않고,
        #     "근거를 찾지 못했다"는 답변이면 근거 부족으로 표시한다(가드레일 (d), 답변 본문은 유지).
        refs = referenced_indices(answer, len(assembled.selected_chunks))
        usage["citation_refs"] = len(refs)
        insufficient = not refs and guardrail.is_no_evidence_answer(answer)
        if insufficient:
            usage["llm_insufficient"] = 1
        citations = build_citations(assembled.selected_chunks, refs)

        return PipelineOutput(
            answer=answer,
            citations=citations,
            insufficient_evidence=insufficient,
            usage=usage,
            selected_chunks=assembled.selected_chunks,
        )

    async def run_direct(
        self,
        *,
        question: str,
        history: list[tuple[str, str]] | None = None,
        on_delta: DeltaCallback | None = None,
    ) -> PipelineOutput:
        """LLM 직접 대화 (FR-CHAT-014) — Embedding·Qdrant·Rerank·가드레일 없이 LLM 만 호출한다.

        검색을 하지 않으므로 Channel 격리(build_filter) 대상이 아니다. 이력은 같은 Token Budget 으로
        오래된 turn 부터 절삭하되, 근거 문서가 없으니 history 상한을 남은 budget 전체로 둔다.
        """
        usage: dict[str, float | int] = {"direct": 1}
        assembled = assemble_context(
            counter=self._counter,
            system_prompt=DIRECT_SYSTEM_PROMPT,
            question=question,
            history=history or [],
            reranked=[],
            config=dataclasses.replace(self._cfg.budget, history_ratio=1.0),
        )
        usage["context_tokens"] = assembled.used_tokens
        messages = build_direct_messages(question=question, history=assembled.history)
        answer = await self._generate(messages, on_delta, usage)
        return PipelineOutput(answer=answer, citations=[], insufficient_evidence=False, usage=usage)

    async def _generate(
        self, messages: list[dict[str, str]], on_delta: DeltaCallback | None, usage: dict
    ) -> str:
        """10-11. vLLM 생성 — on_delta 가 있으면 스트리밍하며 토큰 조각마다 콜백한다."""
        t = time.perf_counter()
        if on_delta is None:
            result = await self._llm.complete(
                messages,
                max_tokens=self._cfg.max_output_tokens,
                temperature=self._cfg.temperature,
            )
            answer = result.text
            usage.update(result.usage)
        else:
            parts: list[str] = []
            async for event in self._llm.stream(
                messages,
                max_tokens=self._cfg.max_output_tokens,
                temperature=self._cfg.temperature,
            ):
                if event.delta:
                    if not parts:
                        usage["llm_first_token_ms"] = _ms(t)
                    parts.append(event.delta)
                    await on_delta(event.delta)
                if event.usage:
                    usage.update(event.usage)
            answer = "".join(parts)
        usage["llm_ms"] = _ms(t)
        return answer


def _ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)


def _insufficient(usage: dict) -> PipelineOutput:
    return PipelineOutput(
        answer=INSUFFICIENT_EVIDENCE_TEXT,
        citations=[],
        insufficient_evidence=True,
        usage=usage,
        selected_chunks=[],
    )
