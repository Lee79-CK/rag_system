"""rag_eval — completions 응답 변환과 지표 (FR-OPS-008). 상세 지표 테스트는 tools/evaluation/tests."""

from __future__ import annotations

from rag_eval import (
    EvalCase,
    GroundTruth,
    case_result_from_completion,
    citation_precision,
    recall_at_10,
)


def _case() -> EvalCase:
    return EvalCase(
        id="c1",
        type="single_doc",
        question="q",
        channel_id="ch",
        ground_truth=GroundTruth(documents=["정답.pdf"], answerable=True),
    )


def _doc(name: str) -> dict:
    return {"document_name": name, "page": 1}


def test_fr_ops_008_recall_uses_retrieved_not_only_citations():
    data = {
        "answer": "a [2]",
        "citations": [_doc("기타.pdf")],
        "retrieved": [_doc("정답.pdf"), _doc("기타.pdf")],
    }
    r = case_result_from_completion(_case(), data)
    assert recall_at_10(r) == 1.0 and citation_precision(r) == 0.0


def test_fr_ops_008_old_rag_api_without_retrieved_falls_back_to_citations():
    r = case_result_from_completion(_case(), {"answer": "a", "citations": [_doc("정답.pdf")]})
    assert [d.document_name for d in r.retrieved] == ["정답.pdf"] and recall_at_10(r) == 1.0
