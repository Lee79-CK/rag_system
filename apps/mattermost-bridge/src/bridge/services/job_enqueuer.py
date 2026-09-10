"""RQ enqueue (docs/TDD.md §7.1.1 step9).

Bridge는 Job id만 enqueue한다. Worker target(`rag.worker.chat_worker.run_chat_job`)은
rag-api 이미지에서 정의된다(문자열 경로 참조 — apps 간 import 금지, §0 규칙 5).
RQ는 동기 Redis 연결을 요구하므로 async redis(dedup/rate-limit용)와 분리한다.
"""

from __future__ import annotations

from typing import Any, Protocol

_QUEUE_NAME = "rag-chat"
_WORKER_TARGET = "rag.worker.chat_worker.run_chat_job"

# RQ 기본 job_timeout(180s) 은 파이프라인 최악치(LLM 120s + embedding/rerank 30s×2 + Qdrant 5s ≈ 185s)
# 보다 짧아 느린 LLM 에서 job 이 중간에 죽고 오류 Post 도 나가지 않는다 → 명시적으로 넉넉히 준다.
JOB_TIMEOUT_SECONDS = 600
RESULT_TTL_SECONDS = 3600
FAILURE_TTL_SECONDS = 86400


def enqueue_chat_job(redis_conn: Any, chat_job_id: str) -> str:
    """`Queue("rag-chat").enqueue(target, chat_job_id, job_timeout=...)` — enqueue된 job id를 반환한다."""
    from rq import Queue

    queue = Queue(_QUEUE_NAME, connection=redis_conn)
    job = queue.enqueue(
        _WORKER_TARGET,
        chat_job_id,
        job_timeout=JOB_TIMEOUT_SECONDS,
        result_ttl=RESULT_TTL_SECONDS,
        failure_ttl=FAILURE_TTL_SECONDS,
    )
    return str(job.id)


class Enqueuer(Protocol):
    """DI 경계 — 테스트에서 스파이로 교체 가능 (§7.1.3 test_fr_mm_006)."""

    def __call__(self, chat_job_id: str) -> str: ...


class RqEnqueuer:
    """운영용 Enqueuer — 동기 Redis 연결로 RQ Queue에 enqueue한다."""

    def __init__(self, connection: Any) -> None:
        self._conn = connection

    def __call__(self, chat_job_id: str) -> str:
        return enqueue_chat_job(self._conn, chat_job_id)
