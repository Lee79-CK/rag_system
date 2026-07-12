"""평가 데이터 모델 (§13.3 dataset schema)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

CaseType = Literal["single_doc", "multi_doc", "table", "definition", "no_answer", "ambiguous"]


class GroundTruth(BaseModel):
    answer_gist: str = ""
    documents: list[str] = Field(default_factory=list)
    pages: list[int] = Field(default_factory=list)
    answerable: bool = True


class EvalCase(BaseModel):
    id: str
    type: CaseType
    question: str
    channel_id: str
    team_id: str = "team-001"
    ground_truth: GroundTruth = Field(default_factory=GroundTruth)


class RetrievedDoc(BaseModel):
    document_name: str
    page: int | None = None


class CaseResult(BaseModel):
    case: EvalCase
    answer: str
    insufficient_evidence: bool
    retrieved: list[RetrievedDoc] = Field(default_factory=list)  # top-K 검색 문서 (citation 기반)
    citations: list[RetrievedDoc] = Field(default_factory=list)
    error: str | None = None


class MetricSummary(BaseModel):
    total: int
    recall_at_10: float
    citation_precision: float
    no_answer_safety: float
    answerable_answered: float
    by_type: dict[str, int] = Field(default_factory=dict)
