"""RQ enqueue 실연동 (fakeredis) — RQ 2.x API 호환 회귀 방지."""

from __future__ import annotations

import fakeredis
from gateway.services.job_enqueuer import RqEnqueuer
from rq import Queue


def test_rq_enqueuer_returns_job_id_and_payload_is_job_id_only():
    conn = fakeredis.FakeRedis()
    job_id = RqEnqueuer(conn)("chat-job-1")
    q = Queue("rag-chat", connection=conn)
    assert job_id in q.job_ids
    job = q.fetch_job(job_id)
    assert job.func_name == "rag.worker.chat_worker.run_chat_job"
    assert job.args == ("chat-job-1",)  # 질문 원문은 Redis chat:req:{id} 로만 전달
