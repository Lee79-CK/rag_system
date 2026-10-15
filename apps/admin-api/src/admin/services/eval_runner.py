"""포털 평가 실행 (FR-OPS-008, TDD §7.5) — 채택(ACCEPTED) 평가셋 후보로 rag-api 동기 completions 를 호출해
문항별 결과·지표(`rag_eval`, CLI runner 와 같은 계산)를 evaluation_runs / evaluation_run_results 에 저장한다.

API 요청은 run 행(RUNNING)만 만들고 응답한다. 실제 실행은 FastAPI BackgroundTasks(threadpool)에서 돈다.
문항은 순차 호출한다 — vLLM 동시 처리 수(max-num-seqs)를 채팅 사용자와 나눠 쓰기 때문.
"""

from __future__ import annotations

import datetime
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

import httpx
from rag_eval import (
    CaseResult,
    EvalCase,
    GroundTruth,
    answerable_answered,
    case_result_from_completion,
    citation_precision,
    no_answer_safe,
    recall_at_10,
    summarize,
)
from rag_observability import get_logger
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from admin.core.config import get_settings
from admin.db.models import EvaluationCandidate, EvaluationRun, EvaluationRunResult
from admin.db.session import get_sessionmaker

log = get_logger("admin.eval_runner")

# 진행 heartbeat(updated_at)가 이 시간 넘게 멈춘 RUNNING 은 중단된 것으로 본다 (파드 재시작 등)
STALE_AFTER = datetime.timedelta(minutes=10)
_ERROR_MAX = 300


class RagCompletions(Protocol):
    def complete(self, channel_id: str, question: str) -> dict[str, Any]: ...


@dataclass(slots=True)
class HttpRagCompletions:
    client: httpx.Client

    def complete(self, channel_id: str, question: str) -> dict[str, Any]:
        resp = self.client.post(
            "/internal/v1/rag/completions", json={"channel_id": channel_id, "message": question}
        )
        resp.raise_for_status()
        return resp.json()


def candidate_case(c: EvaluationCandidate) -> EvalCase:
    """평가셋 후보 → EvalCase (YAML 내보내기와 같은 id 규칙)."""
    return EvalCase(
        id=f"fb-{str(c.id)[:8]}",
        type=c.case_type,  # type: ignore[arg-type]  # DB CHECK 없이 API 가 CaseType 으로 검증
        question=c.question,
        channel_id=c.channel_id,
        ground_truth=GroundTruth(
            answer_gist=c.answer_gist,
            documents=list(c.expected_documents or []),
            pages=list(c.expected_pages or []),
            answerable=c.answerable,
        ),
    )


def _names(docs) -> list[str]:  # type: ignore[no-untyped-def]
    return [d.document_name for d in docs]


def execute_run(
    run_id: uuid.UUID, session_factory: sessionmaker[Session], rag: RagCompletions
) -> None:
    """run_id 의 채택 후보 전체를 평가한다. 문항 실패는 그 문항 error 로 남기고 계속, 그 외 예외는 run FAILED."""
    with session_factory() as db:
        run = db.get(EvaluationRun, run_id)
        if run is None or run.status != "RUNNING":
            return
        try:
            candidates = (
                db.execute(
                    select(EvaluationCandidate)
                    .where(EvaluationCandidate.status == "ACCEPTED")
                    .order_by(EvaluationCandidate.created_at)
                )
                .scalars()
                .all()
            )
            run.total = len(candidates)
            db.commit()
            results: list[CaseResult] = []
            for seq, cand in enumerate(candidates, 1):
                case = candidate_case(cand)
                started = time.perf_counter()
                try:
                    result = case_result_from_completion(
                        case, rag.complete(case.channel_id, case.question)
                    )
                except Exception as exc:  # noqa: BLE001 — 문항 단위 실패는 기록하고 계속 (CLI 와 동일)
                    result = CaseResult(
                        case=case,
                        answer="",
                        insufficient_evidence=False,
                        error=f"{type(exc).__name__}: {exc}"[:_ERROR_MAX],
                    )
                results.append(result)
                db.add(
                    EvaluationRunResult(
                        run_id=run.id,
                        seq=seq,
                        candidate_id=cand.id,
                        case_id=case.id,
                        question=case.question,
                        case_type=case.type,
                        answerable=case.ground_truth.answerable,
                        answer=result.answer,
                        insufficient_evidence=result.insufficient_evidence,
                        expected_documents=case.ground_truth.documents,
                        citations=_names(result.citations),
                        retrieved=_names(result.retrieved),
                        recall_at_10=recall_at_10(result),
                        citation_precision=citation_precision(result),
                        no_answer_safe=no_answer_safe(result),
                        answerable_answered=answerable_answered(result),
                        latency_ms=int((time.perf_counter() - started) * 1000),
                        error=result.error,
                    )
                )
                run.done = seq
                run.updated_at = datetime.datetime.now(datetime.UTC)  # heartbeat
                db.commit()
            # summarize 는 해당 문항이 0건인 지표를 0.0 으로 낸다 → 화면이 "미달"로 오해하지 않게 적용 문항 수를 함께 저장
            applicable = {
                "recall_at_10": sum(recall_at_10(r) is not None for r in results),
                "citation_precision": sum(citation_precision(r) is not None for r in results),
                "no_answer_safety": sum(no_answer_safe(r) is not None for r in results),
                "answerable_answered": sum(answerable_answered(r) is not None for r in results),
            }
            run.metrics = summarize(results).model_dump() | {"applicable": applicable}
            run.status = "COMPLETED"
            run.completed_at = datetime.datetime.now(datetime.UTC)
            db.commit()
            log.info("evaluation_run_completed", run_id=str(run_id), total=run.total)
        except Exception as exc:  # noqa: BLE001 — DB 등 실행 자체 실패
            db.rollback()
            run = db.get(EvaluationRun, run_id)
            if run is not None:
                run.status = "FAILED"
                run.error = f"{type(exc).__name__}: {exc}"[:_ERROR_MAX]
                run.completed_at = datetime.datetime.now(datetime.UTC)
                db.commit()
            log.error("evaluation_run_failed", run_id=str(run_id), error=type(exc).__name__)


@dataclass(slots=True)
class EvalRunner:
    """BackgroundTasks 에 넘기는 실행기. rag-api 클라이언트는 실행마다 열고 닫는다."""

    session_factory: sessionmaker[Session]
    rag_factory: Callable[[], Any]  # () -> context manager yielding RagCompletions

    def __call__(self, run_id: uuid.UUID) -> None:
        with self.rag_factory() as rag:
            execute_run(run_id, self.session_factory, rag)


class _HttpRagContext:
    def __init__(self, base_url: str, timeout: float) -> None:
        self._client = httpx.Client(
            base_url=base_url,
            timeout=httpx.Timeout(connect=3.0, read=timeout, write=10.0, pool=10.0),
        )

    def __enter__(self) -> HttpRagCompletions:
        return HttpRagCompletions(self._client)

    def __exit__(self, *exc: object) -> None:
        self._client.close()


def provide_eval_runner() -> EvalRunner:
    """FastAPI 의존성 — 테스트는 MockTransport 기반 실행기로 override 한다."""
    s = get_settings()
    return EvalRunner(
        session_factory=get_sessionmaker(),
        rag_factory=lambda: _HttpRagContext(s.rag_api_url.rstrip("/"), s.evaluation_timeout),
    )


def _aware(ts: datetime.datetime) -> datetime.datetime:
    return ts if ts.tzinfo else ts.replace(tzinfo=datetime.UTC)  # SQLite(테스트)는 naive


def expire_stale_runs(db: Session, now: datetime.datetime | None = None) -> None:
    """heartbeat 가 멈춘 RUNNING → FAILED. 시작 시 일괄 정리는 다른 replica 의 실행을 죽이므로 조회 시점에 한다."""
    now = now or datetime.datetime.now(datetime.UTC)
    changed = False
    for run in db.execute(select(EvaluationRun).where(EvaluationRun.status == "RUNNING")).scalars():
        if now - _aware(run.updated_at) > STALE_AFTER:
            run.status = "FAILED"
            run.error = "중단됨 — 진행이 10분 넘게 멈춤 (admin-api 재시작 등). 다시 실행하세요."
            run.completed_at = now
            changed = True
    if changed:
        db.commit()
