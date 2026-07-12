"""Context 조립 + Token Budget (§7.2.2, FR-RAG-008).

budget = MAX_CONTEXT_TOKENS - system - question - history - MAX_OUTPUT - SAFETY_MARGIN
- history가 budget의 30%를 초과하면 오래된 turn부터 절삭
- chunk는 rerank 순위대로 budget 소진 시까지 추가, 최소 1개는 보장
"""

from __future__ import annotations

from dataclasses import dataclass, field

from rag.domain.ports import ScoredChunk
from rag.domain.tokens import TokenCounter


@dataclass(slots=True)
class BudgetConfig:
    max_context_tokens: int = 8192
    max_output_tokens: int = 1024
    safety_margin_tokens: int = 256
    history_ratio: float = 0.30


@dataclass(slots=True)
class AssembledContext:
    selected_chunks: list[ScoredChunk]
    history: list[tuple[str, str]]
    used_tokens: int
    chunk_budget: int
    trimmed_history_turns: int = 0
    info: dict = field(default_factory=dict)


def assemble_context(
    *,
    counter: TokenCounter,
    system_prompt: str,
    question: str,
    history: list[tuple[str, str]],
    reranked: list[ScoredChunk],
    config: BudgetConfig,
) -> AssembledContext:
    system_tokens = counter.count(system_prompt)
    question_tokens = counter.count(question)

    reserved = (
        system_tokens + question_tokens + config.max_output_tokens + config.safety_margin_tokens
    )
    remaining = max(0, config.max_context_tokens - reserved)

    # 1) history를 remaining의 history_ratio 이하로 오래된 것부터 절삭.
    history_cap = int(remaining * config.history_ratio)
    kept = list(history)
    trimmed = 0

    def _history_tokens(msgs: list[tuple[str, str]]) -> int:
        return sum(counter.count(content) for _role, content in msgs)

    while kept and _history_tokens(kept) > history_cap:
        kept.pop(0)  # 오래된 turn 먼저 제거
        trimmed += 1
    history_tokens = _history_tokens(kept)

    # 2) chunk budget = remaining - history. rerank 순위대로 채우되 최소 1개 보장.
    chunk_budget = max(0, remaining - history_tokens)
    selected: list[ScoredChunk] = []
    used = 0
    for chunk in reranked:
        ctoks = counter.count(chunk.payload.text)
        if not selected:
            # 최소 1개 보장: budget을 초과해도 top 1은 포함한다.
            selected.append(chunk)
            used += ctoks
            continue
        if used + ctoks > chunk_budget:
            break
        selected.append(chunk)
        used += ctoks

    return AssembledContext(
        selected_chunks=selected,
        history=kept,
        used_tokens=used + history_tokens,
        chunk_budget=chunk_budget,
        trimmed_history_turns=trimmed,
        info={
            "system_tokens": system_tokens,
            "question_tokens": question_tokens,
            "history_tokens": history_tokens,
            "remaining": remaining,
        },
    )
