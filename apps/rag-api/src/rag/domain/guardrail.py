"""근거 부족(Insufficient Evidence) 판정 (§7.2.3, FR-CHAT-004/FR-RAG-010).

발동 조건:
  (a) 검색 결과 0건
  (b) top vector score < SIMILARITY_THRESHOLD
  (c) rerank top score < RERANK_SCORE_THRESHOLD
  → PoC 확정: 이 경우 LLM을 호출하지 않고 고정 안내문을 게시한다.
  (d) 점수는 통과했지만 LLM 이 근거 번호 없이 "근거를 찾지 못했다"고 답한 경우 (생성 후 판정)
  → 답변 본문은 그대로 두고 근거 부족으로 표시(근거 문서 표 없음).
"""

from __future__ import annotations

import re

from rag.domain.ports import RetrievedChunk, ScoredChunk
from rag.domain.prompt import INSUFFICIENT_EVIDENCE_TEXT

# "제공된 문서에서 … 근거나 맥락을 찾지 못했습니다" · "… 정보는 포함되어 있지 않습니다" 류
_NO_EVIDENCE = re.compile(
    r"(근거|정보|내용|맥락|언급|자료|수치)[^.\n]{0,40}?"
    r"(찾지\s*못|찾을\s*수\s*없|확인할\s*수\s*없|확인되지\s*않|포함되어\s*있지\s*않|"
    r"명시되어\s*있지\s*않|나와\s*있지\s*않|언급되어\s*있지\s*않|제공되지\s*않)"
)


def is_insufficient_after_search(
    retrieved: list[RetrievedChunk], similarity_threshold: float
) -> bool:
    if not retrieved:
        return True
    top = max(c.score for c in retrieved)
    return top < similarity_threshold


def is_insufficient_after_rerank(reranked: list[ScoredChunk], rerank_threshold: float) -> bool:
    if not reranked:
        return True
    top = max(c.rerank_score for c in reranked)
    return top < rerank_threshold


def is_no_evidence_answer(answer: str) -> bool:
    """근거 번호를 하나도 인용하지 않은 답변이 "근거를 찾지 못했다"는 취지인지 (조건 d).

    호출자는 근거 번호가 없는 답변에만 쓴다 — "명시되어 있지 않습니다. 다만 … [2, 5]" 같은 부분 답변은
    번호를 인용하므로 여기까지 오지 않는다.
    """
    text = answer.strip()
    return INSUFFICIENT_EVIDENCE_TEXT.rstrip(".") in text or bool(_NO_EVIDENCE.search(text))
