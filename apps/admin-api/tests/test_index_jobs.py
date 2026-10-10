"""색인 작업 조회·재시도 API 테스트 — FR-IDX-005(재시도), FR-IDX-008(Admin Web 진행 조회), PRD §17.8."""

from __future__ import annotations

import datetime as dt
import uuid

from admin.db.models import Document, DocumentVersion, IndexJob


class _SpyTrigger:
    name = "spy"

    def __init__(self) -> None:
        self.calls: list[str] = []

    def trigger(self, index_job_id):
        self.calls.append(index_job_id)
        return "index-job-xyz"


def _spy(client) -> _SpyTrigger:
    from admin.services.index_trigger import provide_index_trigger

    spy = _SpyTrigger()
    client.app.dependency_overrides[provide_index_trigger] = lambda: spy
    return spy


def _upload(client, auth, body: bytes, title: str = "doc") -> str:
    resp = client.post(
        "/api/v1/documents",
        files={"file": (f"{title}.txt", body, "text/plain")},
        data={"title": title},
        headers=auth("docadmin"),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]["document"]["id"]


def _set_status(TestSession, doc_id: str, status: str) -> None:
    with TestSession() as s:
        s.get(Document, uuid.UUID(doc_id)).status = status
        s.commit()


def _add_job(
    TestSession,
    doc_id: str,
    status: str,
    *,
    minutes_ago: int = 0,
    started_minutes_ago: int | None = None,
    error: str | None = None,
    version_id: uuid.UUID | None = None,
) -> str:
    now = dt.datetime.now(dt.UTC)
    with TestSession() as s:
        doc = s.get(Document, uuid.UUID(doc_id))
        job = IndexJob(
            document_version_id=version_id or doc.active_version_id,
            status=status,
            error=error,
            created_at=now - dt.timedelta(minutes=minutes_ago),
            started_at=(
                now - dt.timedelta(minutes=started_minutes_ago)
                if started_minutes_ago is not None
                else None
            ),
        )
        s.add(job)
        s.commit()
        return str(job.id)


def _job(TestSession, job_id: str) -> IndexJob:
    with TestSession() as s:
        return s.get(IndexJob, uuid.UUID(job_id))


def test_fr_idx_008_list_index_jobs_joins_document_and_orders_desc(client, seed, auth, TestSession):
    seed({"docadmin": ["DOC_ADMIN"]})
    a = _upload(client, auth, b"list-a", "manual-a")
    b = _upload(client, auth, b"list-b", "manual-b")
    old = _add_job(TestSession, a, "COMPLETED", minutes_ago=30)
    failed = _add_job(TestSession, b, "FAILED", minutes_ago=10, error="EMBEDDING: timeout")
    stale = _add_job(TestSession, a, "RUNNING", minutes_ago=200, started_minutes_ago=180)
    fresh = _add_job(TestSession, b, "RUNNING", minutes_ago=1, started_minutes_ago=1)

    resp = client.get("/api/v1/index-jobs", headers=auth("docadmin"))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    rows = body["data"]
    assert body["meta"]["count"] == 4
    assert [r["id"] for r in rows] == [fresh, failed, old, stale]  # created_at 내림차순
    by_id = {r["id"]: r for r in rows}
    assert by_id[failed]["document_title"] == "manual-b"
    assert by_id[failed]["document_id"] == b
    assert by_id[failed]["version"] == 1
    assert by_id[failed]["error"] == "EMBEDDING: timeout"
    assert by_id[stale]["stale"] is True and by_id[fresh]["stale"] is False
    assert by_id[old]["stale"] is False
    # 조회는 DB 를 바꾸지 않는다 — stale 도 RUNNING 그대로
    assert _job(TestSession, stale).status == "RUNNING"

    only_failed = client.get("/api/v1/index-jobs?status=failed", headers=auth("docadmin"))
    assert [r["id"] for r in only_failed.json()["data"]] == [failed]

    only_a = client.get(f"/api/v1/index-jobs?document_id={a}", headers=auth("docadmin"))
    assert {r["id"] for r in only_a.json()["data"]} == {old, stale}

    bad = client.get("/api/v1/index-jobs?status=SUCCEEDED", headers=auth("docadmin"))
    assert bad.status_code == 422
    assert bad.json()["error"]["code"] == "INVALID_STATUS"


def test_fr_idx_008_get_index_job_and_404(client, seed, auth, TestSession):
    seed({"docadmin": ["DOC_ADMIN"]})
    doc_id = _upload(client, auth, b"get-one", "manual-get")
    job_id = _add_job(TestSession, doc_id, "COMPLETED")

    resp = client.get(f"/api/v1/index-jobs/{job_id}", headers=auth("docadmin"))
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["document_title"] == "manual-get"

    missing = client.get(f"/api/v1/index-jobs/{uuid.uuid4()}", headers=auth("docadmin"))
    assert missing.status_code == 404


def test_fr_idx_008_index_jobs_require_doc_admin(client, seed, auth, TestSession):
    seed({"docadmin": ["DOC_ADMIN"], "qe": ["QUALITY_EVALUATOR"], "aud": ["AUDITOR"]})
    doc_id = _upload(client, auth, b"rbac", "manual-rbac")
    job_id = _add_job(TestSession, doc_id, "FAILED")

    for user in ("qe", "aud"):
        assert client.get("/api/v1/index-jobs", headers=auth(user)).status_code == 403
        retry = client.post(f"/api/v1/index-jobs/{job_id}/retry", headers=auth(user))
        assert retry.status_code == 403


def test_fr_idx_005_retry_failed_job_creates_new_job(client, seed, auth, TestSession):
    spy = _spy(client)
    seed({"docadmin": ["DOC_ADMIN"]})
    doc_id = _upload(client, auth, b"retry-failed", "manual-retry")
    _set_status(TestSession, doc_id, "INDEXING")  # 색인 실패 시 문서는 INDEXING 에 남는다
    failed = _add_job(TestSession, doc_id, "FAILED", error="PARSING: broken pdf")

    resp = client.post(f"/api/v1/index-jobs/{failed}/retry", headers=auth("docadmin"))
    assert resp.status_code == 202, resp.text
    data = resp.json()["data"]
    new = data["index_job_id"]
    assert new != failed and spy.calls == [new]
    assert data["status"] == "PENDING" and data["trigger"] == "spy"
    assert _job(TestSession, failed).status == "FAILED"  # 원 Job 은 이력으로 유지
    assert _job(TestSession, new).status == "PENDING"


def test_fr_idx_005_retry_trigger_failed_pending_job(client, seed, auth, TestSession):
    spy = _spy(client)
    seed({"docadmin": ["DOC_ADMIN"]})
    doc_id = _upload(client, auth, b"retry-trigger-failed", "manual-tf")
    _set_status(TestSession, doc_id, "INDEXING")
    stuck = _add_job(TestSession, doc_id, "PENDING", error="TRIGGER_FAILED[k8s]: 403")

    resp = client.post(f"/api/v1/index-jobs/{stuck}/retry", headers=auth("docadmin"))
    assert resp.status_code == 202, resp.text
    assert len(spy.calls) == 1
    old = _job(TestSession, stuck)
    assert old.status == "CANCELLED" and old.error.startswith("SUPERSEDED")


def test_fr_idx_005_retry_rejects_non_retryable_and_running(client, seed, auth, TestSession):
    spy = _spy(client)
    seed({"docadmin": ["DOC_ADMIN"]})
    doc_id = _upload(client, auth, b"retry-reject", "manual-reject")
    _set_status(TestSession, doc_id, "ACTIVE")
    for status in ("COMPLETED", "RUNNING"):
        job_id = _add_job(TestSession, doc_id, status, started_minutes_ago=1)
        resp = client.post(f"/api/v1/index-jobs/{job_id}/retry", headers=auth("docadmin"))
        assert resp.status_code == 409, status
        assert resp.json()["error"]["code"] == "INDEX_JOB_NOT_RETRYABLE"

    # 같은 문서에 RUNNING 이 있으면 실패 Job 재시도도 막힌다(중복 색인 방지)
    failed = _add_job(TestSession, doc_id, "FAILED")
    resp = client.post(f"/api/v1/index-jobs/{failed}/retry", headers=auth("docadmin"))
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "INDEX_JOB_RUNNING"
    assert spy.calls == []


def test_fr_idx_005_retry_rejects_superseded_deleted_inactive(client, seed, auth, TestSession):
    spy = _spy(client)
    seed({"docadmin": ["DOC_ADMIN"]})

    # 이전 버전의 실패 Job → 현재 버전을 덮어쓰지 않도록 거부
    doc_id = _upload(client, auth, b"retry-superseded", "manual-v")
    with TestSession() as s:
        doc = s.get(Document, uuid.UUID(doc_id))
        v1 = doc.active_version_id
        v2 = DocumentVersion(
            document_id=doc.id, version=2, hash="h2", file_path="x", file_size=1, status="ACTIVE"
        )
        s.add(v2)
        s.flush()
        doc.active_version_id = v2.id
        doc.status = "ACTIVE"
        s.commit()
    old_version_job = _add_job(TestSession, doc_id, "FAILED", version_id=v1)
    resp = client.post(f"/api/v1/index-jobs/{old_version_job}/retry", headers=auth("docadmin"))
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "INDEX_JOB_SUPERSEDED"

    for doc_status, code in (("DELETED", "DOCUMENT_DELETED"), ("INACTIVE", "DOCUMENT_INACTIVE")):
        d = _upload(client, auth, f"retry-{doc_status}".encode(), f"manual-{doc_status}")
        job_id = _add_job(TestSession, d, "FAILED")
        _set_status(TestSession, d, doc_status)
        resp = client.post(f"/api/v1/index-jobs/{job_id}/retry", headers=auth("docadmin"))
        assert resp.status_code == 409, doc_status
        assert resp.json()["error"]["code"] == code
    assert spy.calls == []
