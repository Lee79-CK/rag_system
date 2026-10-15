"""RAG 품질 평가 공용 모델·지표 (§13.3, PRD §8.1). 순수 Python + pydantic — 네트워크·DB 비종속."""

from rag_eval.completion import case_result_from_completion
from rag_eval.metrics import (
    answerable_answered,
    citation_precision,
    no_answer_safe,
    recall_at_10,
    summarize,
)
from rag_eval.models import (
    CaseResult,
    CaseType,
    EvalCase,
    GroundTruth,
    MetricSummary,
    RetrievedDoc,
)

__all__ = [
    "CaseResult",
    "CaseType",
    "EvalCase",
    "GroundTruth",
    "MetricSummary",
    "RetrievedDoc",
    "answerable_answered",
    "case_result_from_completion",
    "citation_precision",
    "no_answer_safe",
    "recall_at_10",
    "summarize",
]
