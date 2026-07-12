"""evaluation 지표 단위 테스트 (§13.3)."""

from __future__ import annotations

from evaluation.dataset import load_dataset
from evaluation.metrics import (
    citation_precision,
    no_answer_safe,
    recall_at_10,
    summarize,
)
from evaluation.models import CaseResult, EvalCase, GroundTruth, RetrievedDoc


def _case(answerable=True, docs=None, ctype="single_doc"):
    return EvalCase(
        id="q",
        type=ctype,
        question="질문",
        channel_id="channel-001",
        ground_truth=GroundTruth(documents=docs or [], answerable=answerable),
    )


def test_recall_at_10_hit_and_miss():
    hit = CaseResult(
        case=_case(docs=["장애대응매뉴얼.pdf"]),
        answer="a",
        insufficient_evidence=False,
        retrieved=[RetrievedDoc(document_name="장애대응매뉴얼")],
    )
    miss = CaseResult(
        case=_case(docs=["장애대응매뉴얼.pdf"]),
        answer="a",
        insufficient_evidence=False,
        retrieved=[RetrievedDoc(document_name="무관한문서")],
    )
    assert recall_at_10(hit) == 1.0
    assert recall_at_10(miss) == 0.0


def test_recall_none_for_no_answer_case():
    r = CaseResult(case=_case(answerable=False), answer="", insufficient_evidence=True)
    assert recall_at_10(r) is None


def test_citation_precision():
    r = CaseResult(
        case=_case(docs=["장애대응매뉴얼.pdf"]),
        answer="a",
        insufficient_evidence=False,
        citations=[
            RetrievedDoc(document_name="장애대응매뉴얼"),
            RetrievedDoc(document_name="엉뚱한문서"),
        ],
    )
    assert citation_precision(r) == 0.5


def test_no_answer_safety():
    safe = CaseResult(case=_case(answerable=False), answer="근거 없음", insufficient_evidence=True)
    unsafe = CaseResult(
        case=_case(answerable=False), answer="추측답변", insufficient_evidence=False
    )
    assert no_answer_safe(safe) == 1.0
    assert no_answer_safe(unsafe) == 0.0


def test_summarize_aggregates():
    results = [
        CaseResult(
            case=_case(docs=["a.pdf"]),
            answer="x",
            insufficient_evidence=False,
            retrieved=[RetrievedDoc(document_name="a")],
            citations=[RetrievedDoc(document_name="a")],
        ),
        CaseResult(case=_case(answerable=False), answer="", insufficient_evidence=True),
    ]
    s = summarize(results)
    assert s.total == 2
    assert s.recall_at_10 == 1.0
    assert s.citation_precision == 1.0
    assert s.no_answer_safety == 1.0


def test_dataset_loads_sample_yaml():
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    cases = load_dataset(root / "tests" / "evaluation" / "dataset")
    assert len(cases) >= 6
    ids = {c.id for c in cases}
    assert "q001" in ids
    # no_answer 유형이 하나 이상 존재 (§25.6 분포)
    assert any(not c.ground_truth.answerable for c in cases)
