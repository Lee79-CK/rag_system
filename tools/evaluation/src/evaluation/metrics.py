"""평가 지표 (순수 함수, §13.3 / PRD §8.1). LLM/네트워크 비종속 — 단위 테스트 가능."""

from __future__ import annotations

from evaluation.models import CaseResult, MetricSummary


def _doc_match(name: str, expected: list[str]) -> bool:
    """문서명 부분 일치(확장자·경로 차이 허용)."""
    n = name.lower()
    return any(e.lower().rstrip(".pdf").rstrip() in n or n in e.lower() for e in expected)


def recall_at_10(result: CaseResult) -> float | None:
    """정답 문서가 top-10 검색 결과에 포함되면 1.0. answerable=False는 제외(None)."""
    if not result.case.ground_truth.answerable:
        return None
    expected = result.case.ground_truth.documents
    if not expected:
        return None
    top10 = result.retrieved[:10]
    hit = any(_doc_match(d.document_name, expected) for d in top10)
    return 1.0 if hit else 0.0


def citation_precision(result: CaseResult) -> float | None:
    """표시된 citation 중 실제 근거(ground truth 문서)에 해당하는 비율."""
    if not result.case.ground_truth.answerable:
        return None
    if not result.citations:
        return None
    expected = result.case.ground_truth.documents
    if not expected:
        return None
    correct = sum(1 for c in result.citations if _doc_match(c.document_name, expected))
    return correct / len(result.citations)


def no_answer_safe(result: CaseResult) -> float | None:
    """answerable=False 케이스에서 추측 없이 근거 부족을 안내했으면 1.0."""
    if result.case.ground_truth.answerable:
        return None
    return 1.0 if result.insufficient_evidence else 0.0


def answerable_answered(result: CaseResult) -> float | None:
    """answerable=True 케이스에서 실제로 답변(근거 있음)했으면 1.0."""
    if not result.case.ground_truth.answerable:
        return None
    return 0.0 if result.insufficient_evidence else 1.0


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def summarize(results: list[CaseResult]) -> MetricSummary:
    def collect(fn):
        return [v for r in results if (v := fn(r)) is not None]

    by_type: dict[str, int] = {}
    for r in results:
        by_type[r.case.type] = by_type.get(r.case.type, 0) + 1

    return MetricSummary(
        total=len(results),
        recall_at_10=_mean(collect(recall_at_10)),
        citation_precision=_mean(collect(citation_precision)),
        no_answer_safety=_mean(collect(no_answer_safe)),
        answerable_answered=_mean(collect(answerable_answered)),
        by_type=by_type,
    )
