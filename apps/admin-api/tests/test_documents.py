"""문서 업로드/중복/ACL/색인 트리거 테스트 — FR-DOC-002/003/004, FR-IDX-010."""

from __future__ import annotations


def test_document_upload_happy_path(client, seed, auth):
    seed({"docadmin": ["DOC_ADMIN"]})
    resp = client.post(
        "/api/v1/documents",
        files={"file": ("policy.pdf", b"hello-world-content", "application/pdf")},
        data={"title": "정책 문서", "category": "HR"},
        headers=auth("docadmin"),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["data"]["document"]["title"] == "정책 문서"
    assert body["data"]["version"]["version"] == 1
    assert body["data"]["version"]["hash"].startswith("sha256:")
    # envelope 형태 검증.
    assert "meta" in body


def test_fr_doc_003_duplicate_hash_rejected(client, seed, auth):
    seed({"docadmin": ["DOC_ADMIN"]})
    content = b"identical-bytes-for-hash-collision-check"

    first = client.post(
        "/api/v1/documents",
        files={"file": ("a.txt", content, "text/plain")},
        headers=auth("docadmin"),
    )
    assert first.status_code == 201, first.text

    second = client.post(
        "/api/v1/documents",
        files={"file": ("b.txt", content, "text/plain")},
        headers=auth("docadmin"),
    )
    assert second.status_code == 409, second.text
    assert second.json()["error"]["code"] == "DUPLICATE_DOCUMENT"


def test_upload_rejects_bad_extension(client, seed, auth):
    seed({"docadmin": ["DOC_ADMIN"]})
    resp = client.post(
        "/api/v1/documents",
        files={"file": ("evil.exe", b"MZ...", "application/octet-stream")},
        headers=auth("docadmin"),
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "UNSUPPORTED_FILE_TYPE"


def _make_channels(TestSession, *names: str) -> list[str]:
    from admin.db.models import ChatChannel

    with TestSession() as s:
        chans = [ChatChannel(name=n, display_name=n) for n in names]
        s.add_all(chans)
        s.commit()
        return [str(c.id) for c in chans]


def test_fr_doc_004_upload_writes_channel_acl(client, seed, auth, TestSession):
    """allowed_channel_ids 가 document_channel_acl 로 저장되어야 색인 후 해당 채널에서 검색된다.

    admin-web 은 반복 필드, curl 은 콤마 구분 — 둘 다 허용하고 중복은 제거한다.
    """
    import uuid

    from admin.db.models import DocumentChannelAcl

    seed({"docadmin": ["DOC_ADMIN"]})
    c1, c2 = _make_channels(TestSession, "rag-cloud-ops", "rag-hr")
    resp = client.post(
        "/api/v1/documents",
        files={"file": ("manual.md", "# 장애대응\n1등급...".encode(), "text/markdown")},
        data={"title": "장애대응매뉴얼", "allowed_channel_ids": f"{c1}, {c2},{c1}"},
        headers=auth("docadmin"),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()["data"]
    assert body["allowed_channel_ids"] == [c1, c2]
    with TestSession() as s:
        rows = (
            s.query(DocumentChannelAcl)
            .filter_by(document_id=uuid.UUID(body["document"]["id"]))
            .all()
        )
    assert sorted(r.channel_id for r in rows) == sorted([c1, c2])


def test_upload_rejects_non_uuid_channel_id(client, seed, auth):
    """Mattermost 시절 문자열 id(channel-001) 는 격리 키가 아니므로 422."""
    seed({"docadmin": ["DOC_ADMIN"]})
    resp = client.post(
        "/api/v1/documents",
        files={"file": ("x.txt", b"legacy-id", "text/plain")},
        data={"allowed_channel_ids": "channel-001"},
        headers=auth("docadmin"),
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "INVALID_CHANNEL_ID"


def test_fr_idx_010_upload_with_start_indexing_creates_job_and_records_trigger_failure(
    client, seed, auth, TestSession
):
    """start_indexing=true → index_jobs 행 생성 + 트리거 호출. 트리거 실패는 job.error 로 노출(202/201 유지)."""
    from admin.db.models import IndexJob
    from admin.services.index_trigger import IndexTriggerError, provide_index_trigger

    class FailingTrigger:
        name = "k8s"

        def trigger(self, index_job_id):
            raise IndexTriggerError("Job 생성 실패: HTTPStatusError status=403")

    client.app.dependency_overrides[provide_index_trigger] = lambda: FailingTrigger()
    seed({"docadmin": ["DOC_ADMIN"]})
    (cid,) = _make_channels(TestSession, "rag-idx")
    resp = client.post(
        "/api/v1/documents",
        files={"file": ("p.txt", b"content-for-indexing", "text/plain")},
        data={"start_indexing": "true", "allowed_channel_ids": [cid]},
        headers=auth("docadmin"),
    )
    assert resp.status_code == 201, resp.text
    job_id = resp.json()["data"]["index_job_id"]
    with TestSession() as s:
        job = s.get(IndexJob, __import__("uuid").UUID(job_id))
    assert job is not None
    assert job.status == "PENDING"
    assert job.error and job.error.startswith("TRIGGER_FAILED[k8s]")


def test_reindex_calls_trigger(client, seed, auth):
    from admin.services.index_trigger import provide_index_trigger

    calls: list[str] = []

    class SpyTrigger:
        name = "spy"

        def trigger(self, index_job_id):
            calls.append(index_job_id)
            return "index-job-xyz"

    client.app.dependency_overrides[provide_index_trigger] = lambda: SpyTrigger()
    seed({"docadmin": ["DOC_ADMIN"]})
    up = client.post(
        "/api/v1/documents",
        files={"file": ("r.txt", b"reindex-me", "text/plain")},
        headers=auth("docadmin"),
    )
    doc_id = up.json()["data"]["document"]["id"]
    resp = client.post(f"/api/v1/documents/{doc_id}/reindex", headers=auth("docadmin"))
    assert resp.status_code == 202, resp.text
    assert calls == [resp.json()["data"]["index_job_id"]]
    assert resp.json()["data"]["trigger"] == "spy"


def test_upload_registers_channel_acl(client, seed, auth, TestSession):
    """allowed_channel_ids → document_channel_acl (Qdrant 격리 필터의 근거)."""
    from admin.db.models import ChatChannel, DocumentChannelAcl

    seed({"docadmin": ["DOC_ADMIN"]})
    with TestSession() as s:
        ch = ChatChannel(name="rag-hr", display_name="HR")
        s.add(ch)
        s.commit()
        cid = str(ch.id)
    resp = client.post(
        "/api/v1/documents",
        files={"file": ("acl.txt", b"acl body", "text/plain")},
        data={"allowed_channel_ids": [cid]},
        headers=auth("docadmin"),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["data"]["allowed_channel_ids"] == [cid]
    with TestSession() as s:
        rows = s.query(DocumentChannelAcl).all()
        assert [(r.channel_id, r.access_type) for r in rows] == [(cid, "ALLOW")]

    bad = client.post(
        "/api/v1/documents",
        files={"file": ("acl2.txt", b"other body", "text/plain")},
        data={"allowed_channel_ids": ["00000000-0000-0000-0000-000000000000"]},
        headers=auth("docadmin"),
    )
    assert bad.status_code == 404


# ----- PATCH /documents/{id} — 허용 Channel 변경 + 자동 재색인 (FR-DOC-004, PRD §17.8) -----


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


def _upload(client, auth, body: bytes, channel_ids: list[str]) -> str:
    resp = client.post(
        "/api/v1/documents",
        files={"file": ("doc.txt", body, "text/plain")},
        data={"allowed_channel_ids": channel_ids},
        headers=auth("docadmin"),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]["document"]["id"]


def _set_status(TestSession, doc_id: str, status: str) -> None:
    import uuid

    from admin.db.models import Document

    with TestSession() as s:
        s.get(Document, uuid.UUID(doc_id)).status = status
        s.commit()


def _add_job(TestSession, doc_id: str, status: str) -> str:
    import uuid

    from admin.db.models import Document, IndexJob

    with TestSession() as s:
        doc = s.get(Document, uuid.UUID(doc_id))
        job = IndexJob(document_version_id=doc.active_version_id, status=status)
        s.add(job)
        s.commit()
        return str(job.id)


def _acl(TestSession, doc_id: str) -> list[str]:
    import uuid

    from admin.db.models import DocumentChannelAcl

    with TestSession() as s:
        rows = s.query(DocumentChannelAcl).filter_by(document_id=uuid.UUID(doc_id)).all()
        return sorted(r.channel_id for r in rows)


def test_fr_doc_004_patch_replaces_channel_acl_and_triggers_reindex(
    client, seed, auth, TestSession
):
    """기존 문서를 새 채널에 연결(재업로드는 FR-DOC-003 으로 409) → ACL 교체 + 재색인 Job + 감사 diff."""
    from admin.db.models import AuditLog

    spy = _spy(client)
    seed({"docadmin": ["DOC_ADMIN"]})
    ops, hr, reg = _make_channels(TestSession, "rag-cloud-ops", "rag-hr", "ai-regulation")
    doc_id = _upload(client, auth, b"patch-acl-body", [ops, hr])
    _set_status(TestSession, doc_id, "ACTIVE")  # 색인 완료 상태

    resp = client.patch(
        f"/api/v1/documents/{doc_id}",
        json={"allowed_channel_ids": [ops, reg]},
        headers=auth("docadmin"),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["changed"] is True
    assert data["added"] == [reg]
    assert data["removed"] == [hr]
    assert data["document"]["allowed_channel_ids"] == sorted([ops, reg])
    assert data["reindex_skipped_reason"] is None
    assert data["index_job"]["trigger"] == "spy"
    assert spy.calls == [data["index_job"]["index_job_id"]]
    assert _acl(TestSession, doc_id) == sorted([ops, reg])
    with TestSession() as s:
        log = s.query(AuditLog).filter_by(action="DOCUMENT_ACL_UPDATE").one()
    assert log.actor == "docadmin"
    assert log.target == doc_id
    assert log.detail["before"] == sorted([ops, hr])
    assert log.detail["after"] == sorted([ops, reg])


def test_fr_doc_004_patch_unchanged_acl_no_reindex(client, seed, auth, TestSession):
    spy = _spy(client)
    seed({"docadmin": ["DOC_ADMIN"]})
    (ops,) = _make_channels(TestSession, "rag-cloud-ops")
    doc_id = _upload(client, auth, b"unchanged-acl", [ops])
    _set_status(TestSession, doc_id, "ACTIVE")

    resp = client.patch(
        f"/api/v1/documents/{doc_id}", json={"allowed_channel_ids": [ops]}, headers=auth("docadmin")
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["changed"] is False
    assert data["index_job"] is None
    assert spy.calls == []


def test_fr_doc_004_patch_rejects_unknown_or_invalid_channel(client, seed, auth, TestSession):
    _spy(client)
    seed({"docadmin": ["DOC_ADMIN"]})
    (ops,) = _make_channels(TestSession, "rag-cloud-ops")
    doc_id = _upload(client, auth, b"invalid-channel", [ops])

    unknown = client.patch(
        f"/api/v1/documents/{doc_id}",
        json={"allowed_channel_ids": [ops, "00000000-0000-0000-0000-000000000000"]},
        headers=auth("docadmin"),
    )
    assert unknown.status_code == 404
    assert unknown.json()["error"]["code"] == "CHANNEL_NOT_FOUND"
    invalid = client.patch(
        f"/api/v1/documents/{doc_id}",
        json={"allowed_channel_ids": ["channel-001"]},
        headers=auth("docadmin"),
    )
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "INVALID_CHANNEL_ID"
    assert _acl(TestSession, doc_id) == [ops]  # 실패 시 ACL 불변


def test_fr_doc_004_patch_deleted_document_409(client, seed, auth, TestSession):
    _spy(client)
    seed({"docadmin": ["DOC_ADMIN"]})
    (ops,) = _make_channels(TestSession, "rag-cloud-ops")
    doc_id = _upload(client, auth, b"deleted-doc", [])
    _set_status(TestSession, doc_id, "DELETED")

    resp = client.patch(
        f"/api/v1/documents/{doc_id}", json={"allowed_channel_ids": [ops]}, headers=auth("docadmin")
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "DOCUMENT_DELETED"
    assert _acl(TestSession, doc_id) == []


def test_fr_doc_004_patch_running_job_409(client, seed, auth, TestSession):
    """RUNNING Job 은 이전 ACL 을 이미 읽었을 수 있다 → 겹쳐 재색인하지 않고 거부."""
    spy = _spy(client)
    seed({"docadmin": ["DOC_ADMIN"]})
    ops, reg = _make_channels(TestSession, "rag-cloud-ops", "ai-regulation")
    doc_id = _upload(client, auth, b"running-job", [ops])
    _set_status(TestSession, doc_id, "INDEXING")
    job_id = _add_job(TestSession, doc_id, "RUNNING")

    resp = client.patch(
        f"/api/v1/documents/{doc_id}",
        json={"allowed_channel_ids": [ops, reg]},
        headers=auth("docadmin"),
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "INDEX_JOB_RUNNING"
    assert resp.json()["error"]["detail"]["index_job_id"] == job_id
    assert _acl(TestSession, doc_id) == [ops]
    assert spy.calls == []


def test_fr_doc_004_patch_pending_job_reused(client, seed, auth, TestSession):
    """PENDING Job 은 실행 시 ACL 을 읽으므로 새 Job 을 만들지 않고 그 Job 을 돌려준다."""
    spy = _spy(client)
    seed({"docadmin": ["DOC_ADMIN"]})
    ops, reg = _make_channels(TestSession, "rag-cloud-ops", "ai-regulation")
    doc_id = _upload(client, auth, b"pending-job", [ops])
    _set_status(TestSession, doc_id, "INDEXING")
    job_id = _add_job(TestSession, doc_id, "PENDING")

    resp = client.patch(
        f"/api/v1/documents/{doc_id}",
        json={"allowed_channel_ids": [ops, reg]},
        headers=auth("docadmin"),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["index_job"]["index_job_id"] == job_id
    assert data["reindex_skipped_reason"] == "PENDING_JOB_REUSED"
    assert spy.calls == []
    assert _acl(TestSession, doc_id) == sorted([ops, reg])


def test_fr_doc_004_patch_failed_indexing_status_still_reindexes(client, seed, auth, TestSession):
    """색인 실패 문서는 documents.status=INDEXING 에 남는다 — Job 이 FAILED 면 ACL 변경 + 재색인 허용."""
    spy = _spy(client)
    seed({"docadmin": ["DOC_ADMIN"]})
    ops, reg = _make_channels(TestSession, "rag-cloud-ops", "ai-regulation")
    doc_id = _upload(client, auth, b"failed-job", [ops])
    _set_status(TestSession, doc_id, "INDEXING")
    _add_job(TestSession, doc_id, "FAILED")

    resp = client.patch(
        f"/api/v1/documents/{doc_id}",
        json={"allowed_channel_ids": [reg]},
        headers=auth("docadmin"),
    )
    assert resp.status_code == 200, resp.text
    assert len(spy.calls) == 1


def test_fr_doc_004_patch_inactive_or_unindexed_skips_reindex(client, seed, auth, TestSession):
    """INACTIVE 재색인은 ACTIVE 로 되살리고, UPLOADED 는 미색인 → ACL 만 저장."""
    spy = _spy(client)
    seed({"docadmin": ["DOC_ADMIN"]})
    ops, reg = _make_channels(TestSession, "rag-cloud-ops", "ai-regulation")
    uploaded = _upload(client, auth, b"never-indexed", [ops])
    inactive = _upload(client, auth, b"inactive-doc", [ops])
    _set_status(TestSession, inactive, "INACTIVE")

    for doc_id, reason in ((uploaded, "STATUS_UPLOADED"), (inactive, "STATUS_INACTIVE")):
        resp = client.patch(
            f"/api/v1/documents/{doc_id}",
            json={"allowed_channel_ids": [ops, reg]},
            headers=auth("docadmin"),
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["changed"] is True
        assert data["index_job"] is None
        assert data["reindex_skipped_reason"] == reason
        assert _acl(TestSession, doc_id) == sorted([ops, reg])
    assert spy.calls == []


def test_fr_doc_004_patch_requires_doc_admin(client, seed, auth, TestSession):
    _spy(client)
    seed({"docadmin": ["DOC_ADMIN"], "auditor": ["AUDITOR"]})
    (ops,) = _make_channels(TestSession, "rag-cloud-ops")
    doc_id = _upload(client, auth, b"rbac-doc", [])
    resp = client.patch(
        f"/api/v1/documents/{doc_id}", json={"allowed_channel_ids": [ops]}, headers=auth("auditor")
    )
    assert resp.status_code == 403
    assert _acl(TestSession, doc_id) == []


def test_fr_doc_004_get_includes_allowed_channel_ids(client, seed, auth, TestSession):
    seed({"docadmin": ["DOC_ADMIN"]})
    ops, hr = _make_channels(TestSession, "rag-cloud-ops", "rag-hr")
    a = _upload(client, auth, b"doc-a", [ops, hr])
    b = _upload(client, auth, b"doc-b", [])

    listed = {
        d["id"]: d["allowed_channel_ids"]
        for d in client.get("/api/v1/documents", headers=auth("docadmin")).json()["data"]
    }
    assert listed == {a: sorted([ops, hr]), b: []}
    detail = client.get(f"/api/v1/documents/{a}", headers=auth("docadmin")).json()["data"]
    assert detail["allowed_channel_ids"] == sorted([ops, hr])


def test_fr_doc_003_duplicate_detail_includes_existing_status(client, seed, auth, TestSession):
    """409 detail 의 제목·상태로 admin-web 이 '기존 문서에 채널 연결'을 제안한다(DELETED 는 제외)."""
    seed({"docadmin": ["DOC_ADMIN"]})
    doc_id = _upload(client, auth, b"dup-detail-body", [])
    resp = client.post(
        "/api/v1/documents",
        files={"file": ("again.txt", b"dup-detail-body", "text/plain")},
        headers=auth("docadmin"),
    )
    assert resp.status_code == 409
    detail = resp.json()["error"]["detail"]
    assert detail["existing_document_id"] == doc_id
    assert detail["existing_document_title"] == "doc.txt"
    assert detail["existing_document_status"] == "UPLOADED"


# ----- 비활성화·삭제 → 검색 즉시 제외 / 재활성화 (FR-DOC-008) -----


class _FakeSearchIndex:
    def __init__(self, fail: bool = False) -> None:
        self.deactivated: list[str] = []
        self.fail = fail

    def deactivate_document(self, document_id):
        from admin.services.search_index import SearchIndexError

        if self.fail:
            raise SearchIndexError("ConnectError: qdrant down")
        self.deactivated.append(document_id)


def _search(client, fail: bool = False) -> _FakeSearchIndex:
    from admin.services.search_index import provide_search_index

    fake = _FakeSearchIndex(fail)
    client.app.dependency_overrides[provide_search_index] = lambda: fake
    return fake


def _status(TestSession, doc_id: str) -> str:
    import uuid

    from admin.db.models import Document

    with TestSession() as s:
        return s.get(Document, uuid.UUID(doc_id)).status


def _job_status(TestSession, job_id: str) -> str:
    import uuid

    from admin.db.models import IndexJob

    with TestSession() as s:
        return s.get(IndexJob, uuid.UUID(job_id)).status


def test_fr_doc_008_deactivate_excludes_from_search_and_cancels_pending(
    client, seed, auth, TestSession
):
    """DB 상태만 바꾸면 rag-api(Qdrant payload 만 필터)가 계속 인용한다 → is_active=false 를 먼저 반영."""
    _spy(client)
    search = _search(client)
    seed({"docadmin": ["DOC_ADMIN"]})
    doc_id = _upload(client, auth, b"deactivate-me", [])
    _set_status(TestSession, doc_id, "ACTIVE")
    pending = _add_job(TestSession, doc_id, "PENDING")

    resp = client.post(f"/api/v1/documents/{doc_id}/deactivate", headers=auth("docadmin"))
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["status"] == "INACTIVE"
    assert search.deactivated == [doc_id]
    assert _job_status(TestSession, pending) == "CANCELLED"

    again = client.post(f"/api/v1/documents/{doc_id}/deactivate", headers=auth("docadmin"))
    assert again.status_code == 200
    assert search.deactivated == [doc_id]  # 멱등 — 이미 INACTIVE 면 재호출 없음


def test_fr_doc_008_delete_excludes_from_search(client, seed, auth, TestSession):
    _spy(client)
    search = _search(client)
    seed({"docadmin": ["DOC_ADMIN"]})
    doc_id = _upload(client, auth, b"delete-me", [])
    _set_status(TestSession, doc_id, "ACTIVE")

    resp = client.delete(f"/api/v1/documents/{doc_id}", headers=auth("docadmin"))
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["status"] == "DELETED"
    assert search.deactivated == [doc_id]
    assert _status(TestSession, doc_id) == "DELETED"


def test_fr_doc_008_search_index_failure_keeps_status(client, seed, auth, TestSession):
    """Qdrant 갱신 실패 시 503 + DB 불변 — 화면은 '제외됨'인데 실제 검색되는 불일치를 만들지 않는다."""
    _spy(client)
    _search(client, fail=True)
    seed({"docadmin": ["DOC_ADMIN"]})
    doc_id = _upload(client, auth, b"qdrant-down", [])
    _set_status(TestSession, doc_id, "ACTIVE")

    for resp in (
        client.post(f"/api/v1/documents/{doc_id}/deactivate", headers=auth("docadmin")),
        client.delete(f"/api/v1/documents/{doc_id}", headers=auth("docadmin")),
    ):
        assert resp.status_code == 503
        assert resp.json()["error"]["code"] == "SEARCH_INDEX_UNAVAILABLE"
    assert _status(TestSession, doc_id) == "ACTIVE"


def test_fr_doc_008_deactivate_rejected_while_index_job_running(client, seed, auth, TestSession):
    """RUNNING Job 은 끝나면 is_active=true upsert + ACTIVE 로 되돌린다 → 완료 후 재시도."""
    _spy(client)
    search = _search(client)
    seed({"docadmin": ["DOC_ADMIN"]})
    doc_id = _upload(client, auth, b"running-deactivate", [])
    _set_status(TestSession, doc_id, "INDEXING")
    _add_job(TestSession, doc_id, "RUNNING")

    resp = client.post(f"/api/v1/documents/{doc_id}/deactivate", headers=auth("docadmin"))
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "INDEX_JOB_RUNNING"
    assert search.deactivated == []
    assert _status(TestSession, doc_id) == "INDEXING"


def test_fr_doc_009_reindex_rejects_inactive_and_deleted(client, seed, auth, TestSession):
    """재색인은 activate_version 으로 ACTIVE 를 되살리므로 비활성/삭제 문서는 거부."""
    spy = _spy(client)
    seed({"docadmin": ["DOC_ADMIN"]})
    inactive = _upload(client, auth, b"reindex-inactive", [])
    deleted = _upload(client, auth, b"reindex-deleted", [])
    _set_status(TestSession, inactive, "INACTIVE")
    _set_status(TestSession, deleted, "DELETED")

    r1 = client.post(f"/api/v1/documents/{inactive}/reindex", headers=auth("docadmin"))
    assert r1.status_code == 409 and r1.json()["error"]["code"] == "DOCUMENT_INACTIVE"
    r2 = client.post(f"/api/v1/documents/{deleted}/reindex", headers=auth("docadmin"))
    assert r2.status_code == 409 and r2.json()["error"]["code"] == "DOCUMENT_DELETED"
    assert spy.calls == []


def test_fr_doc_008_activate_reindexes_inactive_document(client, seed, auth, TestSession):
    """재활성화 = 재색인 — 비활성 중 바뀐 ACL 까지 현재 값으로 payload 를 다시 쓴다."""
    spy = _spy(client)
    seed({"docadmin": ["DOC_ADMIN"]})
    doc_id = _upload(client, auth, b"activate-me", [])
    _set_status(TestSession, doc_id, "INACTIVE")

    resp = client.post(f"/api/v1/documents/{doc_id}/activate", headers=auth("docadmin"))
    assert resp.status_code == 202, resp.text
    assert spy.calls == [resp.json()["data"]["index_job_id"]]
    assert _status(TestSession, doc_id) == "INDEXING"

    not_inactive = client.post(f"/api/v1/documents/{doc_id}/activate", headers=auth("docadmin"))
    assert not_inactive.status_code == 409
    assert not_inactive.json()["error"]["code"] == "DOCUMENT_NOT_INACTIVE"
