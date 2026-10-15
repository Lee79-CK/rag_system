"""평가(Evaluation) API — docs/TDD.md §7.5, §13.3. 접근 역할: SYS_ADMIN, QUALITY_EVALUATOR.

👎 답변을 평가셋 후보로 승격하고, 평가자가 정답(ground_truth)을 채워 채택한 후보를
`tools/evaluation` runner 가 읽는 YAML(§13.3)로 내보낸다. 채택 후보는 포털에서 바로 평가 실행할 수도 있다(FR-OPS-008).

- POST  /api/v1/evaluation/candidates          {message_id} → 후보 생성(이미 있으면 기존 후보, 멱등)
- GET   /api/v1/evaluation/candidates?status=  후보 목록 (최신순)
- PATCH /api/v1/evaluation/candidates/{id}     유형·정답 요지·기대 문서/쪽·answerable·상태·메모 수정
- GET   /api/v1/evaluation/candidates/export   ACCEPTED 후보 → YAML 파일 (runner dataset 디렉터리에 그대로 둔다)
- POST  /api/v1/evaluation/runs                ACCEPTED 후보로 평가 실행 시작 (202, 백그라운드 — services/eval_runner.py)
- GET   /api/v1/evaluation/runs                실행 이력 (최신순, 지표·진행률)
- GET   /api/v1/evaluation/runs/{id}           실행 + 문항별 결과
"""

from __future__ import annotations

import json
import uuid
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from admin.api.responses import api_error, envelope
from admin.core.rbac import QUALITY_EVALUATOR, SYS_ADMIN, Principal, require_roles
from admin.db.models import (
    ChatJob,
    ChatPost,
    Citation,
    Document,
    EvaluationCandidate,
    EvaluationRun,
    EvaluationRunResult,
    Message,
    MessageFeedbackRow,
)
from admin.db.session import get_db
from admin.services.eval_runner import EvalRunner, expire_stale_runs, provide_eval_runner

router = APIRouter(prefix="/api/v1/evaluation", tags=["evaluation"])

_ROLES = (SYS_ADMIN, QUALITY_EVALUATOR)

# tools/evaluation `CaseType` 과 동일 (§13.3)
CaseType = Literal["single_doc", "multi_doc", "table", "definition", "no_answer", "ambiguous"]
CandidateStatus = Literal["PENDING", "ACCEPTED", "REJECTED"]


class PromoteRequest(BaseModel):
    message_id: uuid.UUID


class CandidateUpdate(BaseModel):
    case_type: CaseType | None = None
    answer_gist: str | None = Field(default=None, max_length=2000)
    expected_documents: list[str] | None = Field(default=None, max_length=20)
    expected_pages: list[int] | None = Field(default=None, max_length=50)
    answerable: bool | None = None
    status: CandidateStatus | None = None
    note: str | None = Field(default=None, max_length=2000)


def _view(c: EvaluationCandidate) -> dict:
    return {
        "id": str(c.id),
        "message_id": str(c.message_id) if c.message_id else None,
        "channel_id": c.channel_id,
        "question": c.question,
        "answer": c.answer,
        "cited_documents": c.cited_documents or [],
        "case_type": c.case_type,
        "answer_gist": c.answer_gist,
        "expected_documents": c.expected_documents or [],
        "expected_pages": c.expected_pages or [],
        "answerable": c.answerable,
        "status": c.status,
        "note": c.note,
        "promoted_by": c.promoted_by,
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "updated_at": c.updated_at.isoformat() if c.updated_at else None,
    }


def question_for(db: Session, answer: Message) -> str | None:
    """답변(assistant message)의 질문 원문(트리거어·`/` 제거된 질문).

    답변 message.post_id = Bot Post → chat_jobs(bot_post_id) → 질문 Post → user message.
    CHANNEL 모드에서는 여러 사용자의 질문이 섞일 수 있어 "직전 user 메시지"보다 Job 연결이 정확하다.
    """
    if answer.post_id is None:
        return None
    job = db.execute(
        select(ChatJob).where(ChatJob.bot_post_id == answer.post_id).limit(1)
    ).scalar_one_or_none()
    if job is None or job.post_id is None:
        return None
    user_msg = db.execute(
        select(Message).where(Message.post_id == job.post_id, Message.role == "user").limit(1)
    ).scalar_one_or_none()
    if user_msg is not None:
        return user_msg.content
    post = db.get(ChatPost, job.post_id)
    return post.message if post else None


def _cited_titles(db: Session, message_id: uuid.UUID) -> list[str]:
    """답변이 인용한 문서 제목(중복 제거, rank 순). runner 는 citation 의 document_name(=제목)으로 비교한다."""
    rows = db.execute(
        select(Document.title)
        .join(Citation, Citation.document_id == Document.id)
        .where(Citation.message_id == message_id)
        .order_by(Citation.rank)
    ).all()
    titles: list[str] = []
    for (title,) in rows:
        if title not in titles:
            titles.append(title)
    return titles


@router.post("/candidates")
def promote_candidate(
    body: PromoteRequest,
    response: Response,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles(*_ROLES)),
) -> dict:
    existing = db.execute(
        select(EvaluationCandidate).where(EvaluationCandidate.message_id == body.message_id)
    ).scalar_one_or_none()
    if existing is not None:
        return envelope(
            {
                "candidate_id": str(existing.id),
                "message_id": str(body.message_id),
                "status": existing.status,
                "created": False,
            }
        )

    msg = db.get(Message, body.message_id)
    if msg is None:
        raise api_error("NOT_FOUND", "메시지를 찾을 수 없습니다.", status.HTTP_404_NOT_FOUND)
    if msg.role != "assistant":
        raise api_error(
            "NOT_AN_ANSWER",
            "챗봇 답변만 평가셋 후보로 승격할 수 있습니다.",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    channel_id = (
        db.execute(
            select(MessageFeedbackRow.channel_id)
            .where(MessageFeedbackRow.message_id == msg.id)
            .limit(1)
        ).scalar_one_or_none()
        or msg.conversation.channel_id
    )
    cited = _cited_titles(db, msg.id)
    candidate = EvaluationCandidate(
        message_id=msg.id,
        channel_id=channel_id,
        question=question_for(db, msg) or "",
        answer=msg.content,
        cited_documents=cited,
        expected_documents=list(cited),  # 평가자가 수정하는 초기값
        promoted_by=principal.login_id,
    )
    db.add(candidate)
    db.commit()
    response.status_code = status.HTTP_201_CREATED
    return envelope(
        {
            "candidate_id": str(candidate.id),
            "message_id": str(msg.id),
            "status": candidate.status,
            "created": True,
        }
    )


@router.get("/candidates")
def list_candidates(
    candidate_status: CandidateStatus | None = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles(*_ROLES)),
) -> dict:
    stmt = select(EvaluationCandidate).order_by(EvaluationCandidate.created_at.desc())
    if candidate_status:
        stmt = stmt.where(EvaluationCandidate.status == candidate_status)
    rows = db.execute(stmt).scalars().all()
    return envelope([_view(c) for c in rows], count=len(rows))


def _yaml_str(value: str) -> str:
    # JSON 문자열은 YAML double-quoted scalar 로도 유효하다 — 한글은 그대로, 줄바꿈·따옴표는 escape.
    return json.dumps(value, ensure_ascii=False)


def to_dataset_yaml(candidates: list[EvaluationCandidate]) -> str:
    """§13.3 EvalCase 목록 YAML. 파일 하나에 여러 문항(list) — runner `load_dataset` 가 지원한다."""
    lines = [
        "# RAG Admin 품질 평가 → 채택(ACCEPTED) 후보 내보내기 (§13.3)",
        "# tests/evaluation/<dataset>/ 에 두고 `make evaluate` (runner --dataset) 로 실행",
    ]
    for c in candidates:
        lines += [
            f"- id: {_yaml_str('fb-' + str(c.id)[:8])}",
            f"  type: {c.case_type}",
            f"  question: {_yaml_str(c.question)}",
            f"  channel_id: {_yaml_str(c.channel_id)}",
            "  ground_truth:",
            f"    answer_gist: {_yaml_str(c.answer_gist)}",
            f"    documents: [{', '.join(_yaml_str(d) for d in c.expected_documents or [])}]",
            f"    pages: [{', '.join(str(int(p)) for p in c.expected_pages or [])}]",
            f"    answerable: {'true' if c.answerable else 'false'}",
        ]
    return "\n".join(lines) + "\n"


@router.get("/candidates/export")
def export_candidates(
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles(*_ROLES)),
) -> Response:
    rows = (
        db.execute(
            select(EvaluationCandidate)
            .where(EvaluationCandidate.status == "ACCEPTED")
            .order_by(EvaluationCandidate.created_at)
        )
        .scalars()
        .all()
    )
    return Response(
        content=to_dataset_yaml(list(rows)),
        media_type="application/yaml; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="feedback-candidates.yaml"'},
    )


@router.patch("/candidates/{candidate_id}")
def update_candidate(
    candidate_id: uuid.UUID,
    body: CandidateUpdate,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles(*_ROLES)),
) -> dict:
    c = db.get(EvaluationCandidate, candidate_id)
    if c is None:
        raise api_error("NOT_FOUND", "평가셋 후보를 찾을 수 없습니다.", status.HTTP_404_NOT_FOUND)
    patch = body.model_dump(exclude_unset=True)
    if patch.get("status") == "ACCEPTED" or (c.status == "ACCEPTED" and "status" not in patch):
        gist = patch.get("answer_gist", c.answer_gist)
        answerable = patch.get("answerable", c.answerable)
        if answerable and not (gist or "").strip():
            raise api_error(
                "ANSWER_GIST_REQUIRED",
                "답변 가능한 문항은 정답 요지를 입력해야 채택할 수 있습니다.",
                status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
    for key, value in patch.items():
        setattr(c, key, value)
    db.commit()
    db.refresh(c)
    return envelope(_view(c))


# ---------------------------------------------------------------- 평가 실행 (FR-OPS-008)
def _iso(ts) -> str | None:  # type: ignore[no-untyped-def]
    return ts.isoformat() if ts else None


def _run_view(r: EvaluationRun) -> dict:
    return {
        "id": str(r.id),
        "status": r.status,
        "dataset": r.dataset,
        "total": r.total,
        "done": r.done,
        "metrics": r.metrics,
        "error": r.error,
        "started_by": r.started_by,
        "created_at": _iso(r.created_at),
        "updated_at": _iso(r.updated_at),
        "completed_at": _iso(r.completed_at),
    }


def _result_view(x: EvaluationRunResult) -> dict:
    return {
        "seq": x.seq,
        "candidate_id": str(x.candidate_id) if x.candidate_id else None,
        "case_id": x.case_id,
        "question": x.question,
        "case_type": x.case_type,
        "answerable": x.answerable,
        "answer": x.answer,
        "insufficient_evidence": x.insufficient_evidence,
        "expected_documents": x.expected_documents or [],
        "citations": x.citations or [],
        "retrieved": x.retrieved or [],
        "recall_at_10": x.recall_at_10,
        "citation_precision": x.citation_precision,
        "no_answer_safe": x.no_answer_safe,
        "answerable_answered": x.answerable_answered,
        "latency_ms": x.latency_ms,
        "error": x.error,
    }


@router.post("/runs", status_code=status.HTTP_202_ACCEPTED)
def start_run(
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    runner: EvalRunner = Depends(provide_eval_runner),
    principal: Principal = Depends(require_roles(*_ROLES)),
) -> dict:
    expire_stale_runs(db)
    if db.execute(select(EvaluationRun.id).where(EvaluationRun.status == "RUNNING")).first():
        raise api_error(
            "EVALUATION_RUNNING",
            "이미 실행 중인 평가가 있습니다. 끝난 뒤 다시 실행하세요.",
            status.HTTP_409_CONFLICT,
        )
    total = db.execute(
        select(func.count())
        .select_from(EvaluationCandidate)
        .where(EvaluationCandidate.status == "ACCEPTED")
    ).scalar_one()
    if total == 0:
        raise api_error(
            "NO_ACCEPTED_CANDIDATES",
            "채택된 평가셋 후보가 없습니다. 후보를 검토해 채택한 뒤 실행하세요.",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    run = EvaluationRun(status="RUNNING", total=total, started_by=principal.login_id)
    db.add(run)
    try:
        db.commit()
    except IntegrityError:  # 다른 replica 가 동시에 시작 — partial unique index(RUNNING 1건)
        db.rollback()
        raise api_error(
            "EVALUATION_RUNNING", "이미 실행 중인 평가가 있습니다.", status.HTTP_409_CONFLICT
        ) from None
    background.add_task(runner, run.id)
    return envelope(_run_view(run))


@router.get("/runs")
def list_runs(
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles(*_ROLES)),
) -> dict:
    expire_stale_runs(db)
    rows = (
        db.execute(select(EvaluationRun).order_by(EvaluationRun.created_at.desc()).limit(limit))
        .scalars()
        .all()
    )
    return envelope([_run_view(r) for r in rows], count=len(rows))


@router.get("/runs/{run_id}")
def get_run(
    run_id: uuid.UUID,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles(*_ROLES)),
) -> dict:
    expire_stale_runs(db)
    run = db.get(EvaluationRun, run_id)
    if run is None:
        raise api_error("NOT_FOUND", "평가 실행을 찾을 수 없습니다.", status.HTTP_404_NOT_FOUND)
    return envelope({**_run_view(run), "results": [_result_view(x) for x in run.results]})
