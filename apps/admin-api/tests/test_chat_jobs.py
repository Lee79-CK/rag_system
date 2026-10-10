"""대화 작업 조회 API — 상태·기간 필터 (사이드바 "최근 실패" 배지, TDD §7.5)."""

from __future__ import annotations

import datetime as dt

from admin.db.models import ChatJob


def _add(TestSession, status: str, hours_ago: float, error: str | None = None) -> str:
    with TestSession() as s:
        job = ChatJob(
            status=status,
            error=error,
            queued_at=dt.datetime.now(dt.UTC) - dt.timedelta(hours=hours_ago),
        )
        s.add(job)
        s.commit()
        return str(job.id)


def test_chat_jobs_filter_by_status_and_recent_hours(client, seed, auth, TestSession):
    seed({"admin": ["SYS_ADMIN"]})
    old_failed = _add(TestSession, "FAILED", hours_ago=48, error="reranker 500")
    recent_failed = _add(TestSession, "FAILED", hours_ago=2, error="LLM timeout")
    recent_ok = _add(TestSession, "COMPLETED", hours_ago=1)

    def ids(query: str) -> list[str]:
        resp = client.get(f"/api/v1/chat-jobs{query}", headers=auth("admin"))
        assert resp.status_code == 200, resp.text
        return [j["id"] for j in resp.json()["data"]]

    # 기존 동작 유지: 필터 없으면 전체, 최신순
    assert ids("") == [recent_ok, recent_failed, old_failed]
    assert set(ids("?job_status=FAILED")) == {recent_failed, old_failed}
    # 배지용: 최근 24시간 실패만 — 오래된 실패는 더 이상 세지 않는다
    assert ids("?job_status=FAILED&since_hours=24") == [recent_failed]
    assert set(ids("?since_hours=24")) == {recent_failed, recent_ok}


def test_chat_jobs_since_hours_validated(client, seed, auth):
    seed({"admin": ["SYS_ADMIN"]})
    assert client.get("/api/v1/chat-jobs?since_hours=0", headers=auth("admin")).status_code == 422
