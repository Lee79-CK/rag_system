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
