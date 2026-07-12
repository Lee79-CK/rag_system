"""평가 리포트 (Markdown) — reports/evaluation_report.md (§13.3)."""

from __future__ import annotations

from evaluation.models import CaseResult, MetricSummary

# PRD §8.1 PoC 목표
TARGETS = {
    "recall_at_10": 0.85,
    "citation_precision": 0.90,
    "no_answer_safety": 0.90,
}


def _pass(value: float, target: float) -> str:
    return "✅" if value >= target else "❌"


def render_report(summary: MetricSummary, results: list[CaseResult]) -> str:
    lines: list[str] = ["# RAG 평가 리포트", ""]
    lines.append(f"- 총 문항: **{summary.total}**")
    lines.append(f"- 유형 분포: {summary.by_type}")
    lines.append("")
    lines.append("## 지표 (PRD §8.1 목표 대비)")
    lines.append("")
    lines.append("| 지표 | 결과 | 목표 | 판정 |")
    lines.append("|---|---:|---:|:--:|")
    lines.append(
        f"| 검색 Recall@10 | {summary.recall_at_10:.1%} | 85% | "
        f"{_pass(summary.recall_at_10, TARGETS['recall_at_10'])} |"
    )
    lines.append(
        f"| Citation Precision | {summary.citation_precision:.1%} | 90% | "
        f"{_pass(summary.citation_precision, TARGETS['citation_precision'])} |"
    )
    lines.append(
        f"| 무근거 안전응답률 | {summary.no_answer_safety:.1%} | 90% | "
        f"{_pass(summary.no_answer_safety, TARGETS['no_answer_safety'])} |"
    )
    lines.append(f"| 근거 응답률(answerable) | {summary.answerable_answered:.1%} | — | — |")
    lines.append("")
    lines.append("## 문항별 결과")
    lines.append("")
    lines.append("| id | type | answerable | 근거부족 | citations | error |")
    lines.append("|---|---|:--:|:--:|---:|---|")
    for r in results:
        lines.append(
            f"| {r.case.id} | {r.case.type} | {r.case.ground_truth.answerable} | "
            f"{r.insufficient_evidence} | {len(r.citations)} | {r.error or ''} |"
        )
    lines.append("")
    return "\n".join(lines)
