"""RAG 파이프라인 오케스트레이션 (§7.2.1). 프레임워크/인프라 비종속.

포트(embed/search/rerank/llm)와 순수 도메인 로직만으로 RagCompletion 재료를 만든다.
대화 이력 로딩·메시지 영속화·Job 상태·게시는 Worker 계층이 담당한다 (도메인 순수성 유지).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from rag_schemas import ChannelBinding, Citation

from rag.domain import guardrail
from rag.domain.citation import build_citations
from rag.domain.context import BudgetConfig, assemble_context
from rag.domain.ports import (
    EmbeddingPort,
    LLMPort,
    RerankPort,
    RetrievalPort,
    RetrievedChunk,
    ScoredChunk,
)
from rag.domain.prompt import INSUFFICIENT_EVIDENCE_TEXT, SYSTEM_PROMPT, build_messages
from rag.domain.retrieval import build_filter


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
    ) -> PipelineOutput:
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

        # 8. Re-rank (후보 → top_n)
        t = time.perf_counter()
        docs = [c.payload.text for c in retrieved]
        ranked = await self._rerank.rerank(question, docs, self._cfg.rerank_top_n)
        reranked = [
            ScoredChunk(
                payload=retrieved[idx].payload,
                vector_score=retrieved[idx].score,
                rerank_score=score,
            )
            for idx, score in ranked
        ]
        usage["rerank_ms"] = _ms(t)

        if guardrail.is_insufficient_after_rerank(reranked, self._cfg.rerank_score_threshold):
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
        t = time.perf_counter()
        result = await self._llm.complete(
            messages,
            max_tokens=self._cfg.max_output_tokens,
            temperature=self._cfg.temperature,
        )
        usage["llm_ms"] = _ms(t)
        usage.update(result.usage)

        # 12. Citation 생성
        citations = build_citations(assembled.selected_chunks)

        return PipelineOutput(
            answer=result.text,
            citations=citations,
            insufficient_evidence=False,
            usage=usage,
            selected_chunks=assembled.selected_chunks,
        )


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
