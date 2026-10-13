"""Citation Trace 생성 (§7.2.1 step12). 답변이 인용한 chunk payload → Citation 목록."""

from __future__ import annotations

import re

from rag_schemas import Citation

from rag.domain.ports import ScoredChunk

_EXCERPT_MAX = 200  # Citation.excerpt 최대 200자 (§4.2)

# 근거 번호 묶음: [2] · [2, 5] · [1-3] · [1~3] (LLM 이 쓰는 형식). [1][3] 은 묶음 2개로 잡힌다.
_REF_GROUP = re.compile(r"\[\s*(\d+(?:\s*[,~\-–]\s*\d+)*)\s*\]")
_REF_TOKEN = re.compile(r"(\d+)\s*[~\-–]\s*(\d+)|(\d+)")


def referenced_indices(answer: str, n: int) -> list[int]:
    """답변 본문에서 인용한 근거 번호(1..n)를 오름차순으로 돌려준다.

    범위를 벗어난 번호(연도 [2025] 등)는 근거 번호가 아니므로 버린다.
    """
    refs: set[int] = set()
    for group in _REF_GROUP.findall(answer):
        for lo, hi, single in _REF_TOKEN.findall(group):
            if single:
                values = [int(single)]
            else:
                a, b = sorted((int(lo), int(hi)))
                values = list(range(a, min(b, n) + 1)) if a <= n else []
            refs.update(v for v in values if 1 <= v <= n)
    return sorted(refs)


def build_citations(chunks: list[ScoredChunk], refs: list[int] | None = None) -> list[Citation]:
    """refs 가 주어지면 그 번호(1부터, 프롬프트 [근거 문서] 순서)의 chunk 만 Citation 으로 만든다."""
    wanted = None if refs is None else set(refs)
    citations: list[Citation] = []
    for i, chunk in enumerate(chunks, 1):
        if wanted is not None and i not in wanted:
            continue
        p = chunk.payload
        excerpt = p.text.strip().replace("\n", " ")
        if len(excerpt) > _EXCERPT_MAX:
            excerpt = excerpt[: _EXCERPT_MAX - 1].rstrip() + "…"
        citations.append(
            Citation(
                document_id=p.document_id,
                document_name=p.title,
                page=p.page_start,
                section=p.section,
                excerpt=excerpt,
                score=chunk.rerank_score,
                chunk_id=p.chunk_id,
                ref=i,
            )
        )
    return citations
