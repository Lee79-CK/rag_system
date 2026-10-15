"""rag-api 동기 completions 응답(`RagCompletion` JSON) → CaseResult (§9, §13.3)."""

from __future__ import annotations

from typing import Any

from rag_eval.models import CaseResult, EvalCase, RetrievedDoc


def _docs(items: list[dict[str, Any]]) -> list[RetrievedDoc]:
    return [RetrievedDoc(document_name=c["document_name"], page=c.get("page")) for c in items]


def case_result_from_completion(case: EvalCase, data: dict[str, Any]) -> CaseResult:
    """`retrieved`(컨텍스트로 선택된 검색 청크)가 없으면 citations 로 근사한다(구버전 rag-api 호환).

    citations 는 답변 본문이 인용한 문서만이므로(FR-CHAT-003) Recall@10 은 retrieved 기준이 정확하다.
    """
    citations = _docs(data.get("citations", []))
    retrieved = _docs(data.get("retrieved", []))
    return CaseResult(
        case=case,
        answer=data.get("answer", ""),
        insufficient_evidence=data.get("insufficient_evidence", False),
        retrieved=retrieved or citations,
        citations=citations,
    )
