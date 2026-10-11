"""여러 파일 일괄 업로드 — FR-DOC-001(업로드)·002(개수·합계 제한)·003(중복은 파일별 실패)."""

from __future__ import annotations

from admin.db.models import Document, DocumentChannelAcl, IndexJob


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


def _channel(TestSession, name: str = "ent") -> str:
    from admin.db.models import ChatChannel

    with TestSession() as s:
        ch = ChatChannel(name=name, display_name=name, type="public")
        s.add(ch)
        s.commit()
        return str(ch.id)


def _batch(client, auth, files: list[tuple[str, bytes]], user: str = "docadmin", **data):
    return client.post(
        "/api/v1/documents/batch",
        files=[("files", (name, body, "application/octet-stream")) for name, body in files],
        data=data,
        headers=auth(user),
    )


def _doc_count(TestSession) -> int:
    with TestSession() as s:
        return s.query(Document).count()


def test_fr_doc_001_batch_upload_creates_each_file_with_shared_metadata(
    client, seed, auth, TestSession
):
    spy = _spy(client)
    seed({"docadmin": ["DOC_ADMIN"]})
    ch = _channel(TestSession)

    resp = _batch(
        client,
        auth,
        [("a.pdf", b"%PDF a"), ("b.txt", "본문 b".encode()), ("c.md", b"# c")],
        category="Entertainment",
        security_level="PUBLIC",
        allowed_channel_ids=[ch],
        start_indexing="true",
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["meta"] == {"created": 3, "failed": 0}
    items = body["data"]
    assert [i["file_name"] for i in items] == ["a.pdf", "b.txt", "c.md"]
    assert all(i["ok"] for i in items)
    assert [i["document"]["title"] for i in items] == ["a.pdf", "b.txt", "c.md"]
    assert {i["document"]["category"] for i in items} == {"Entertainment"}
    assert {i["document"]["security_level"] for i in items} == {"PUBLIC"}
    assert all(i["allowed_channel_ids"] == [ch] for i in items)
    # 문서마다 색인 Job 생성·트리거
    assert len(spy.calls) == 3 and [i["index_job_id"] for i in items] == spy.calls
    with TestSession() as s:
        assert s.query(DocumentChannelAcl).filter_by(channel_id=ch).count() == 3
        assert s.query(IndexJob).count() == 3


def test_fr_doc_003_batch_duplicates_reported_per_file(client, seed, auth, TestSession):
    seed({"docadmin": ["DOC_ADMIN"]})
    first = _batch(client, auth, [("old.pdf", b"same-old")])
    old_id = first.json()["data"][0]["document"]["id"]

    resp = _batch(
        client,
        auth,
        [("new.pdf", b"brand-new"), ("again.pdf", b"same-old"), ("dup-in-batch.pdf", b"brand-new")],
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["meta"] == {"created": 1, "failed": 2}
    new, again, dup = body["data"]
    assert new["ok"] is True
    assert again["ok"] is False and again["error"]["code"] == "DUPLICATE_DOCUMENT"
    assert again["error"]["detail"]["existing_document_id"] == old_id
    assert again["error"]["detail"]["existing_document_title"] == "old.pdf"
    # 같은 배치 안의 동일 내용 파일도 앞 파일과 중복으로 처리
    assert dup["ok"] is False and dup["error"]["code"] == "DUPLICATE_DOCUMENT"
    assert dup["error"]["detail"]["existing_document_id"] == new["document"]["id"]
    assert _doc_count(TestSession) == 2


def test_fr_doc_002_batch_per_file_validation(client, seed, auth, TestSession):
    seed({"docadmin": ["DOC_ADMIN"]})
    resp = _batch(
        client,
        auth,
        [("ok.txt", b"fine"), ("bad.exe", b"MZ"), ("empty.pdf", b"")],
    )
    assert resp.status_code == 200, resp.text
    ok, bad, empty = resp.json()["data"]
    assert ok["ok"] is True
    assert bad["error"]["code"] == "UNSUPPORTED_FILE_TYPE"
    assert empty["error"]["code"] == "EMPTY_FILE"
    assert _doc_count(TestSession) == 1


def test_fr_doc_002_batch_limits(client, seed, auth, TestSession, monkeypatch):
    seed({"docadmin": ["DOC_ADMIN"]})

    too_many = _batch(client, auth, [(f"f{i}.txt", f"body-{i}".encode()) for i in range(11)])
    assert too_many.status_code == 422
    assert too_many.json()["error"]["code"] == "TOO_MANY_FILES"
    assert too_many.json()["error"]["detail"]["max_files"] == 10

    none = client.post("/api/v1/documents/batch", data={}, headers=auth("docadmin"))
    assert none.status_code == 422

    # 합계 상한 — 개별 파일은 상한 이하여도 합이 넘으면 요청 전체 거부, 아무것도 저장 안 함
    from admin.core.config import get_settings

    monkeypatch.setattr(get_settings(), "max_upload_bytes", 10)
    big = _batch(client, auth, [("a.txt", b"123456"), ("b.txt", b"789012")])
    assert big.status_code == 413
    err = big.json()["error"]
    assert err["code"] == "BATCH_TOO_LARGE" and err["detail"]["total_bytes"] == 12
    assert _doc_count(TestSession) == 0


def test_fr_doc_001_batch_title_single_file_only(client, seed, auth, TestSession):
    seed({"docadmin": ["DOC_ADMIN"]})
    multi = _batch(client, auth, [("a.txt", b"a"), ("b.txt", b"b")], title="공통 제목")
    assert multi.status_code == 422
    assert multi.json()["error"]["code"] == "TITLE_SINGLE_FILE_ONLY"

    single = _batch(client, auth, [("c.txt", b"c")], title="단일 제목")
    assert single.status_code == 200
    assert single.json()["data"][0]["document"]["title"] == "단일 제목"


def test_fr_doc_001_batch_rejects_unknown_channel_before_saving(client, seed, auth, TestSession):
    seed({"docadmin": ["DOC_ADMIN"]})
    resp = _batch(
        client,
        auth,
        [("a.txt", b"a")],
        allowed_channel_ids=["00000000-0000-0000-0000-000000000000"],
    )
    assert resp.status_code == 404
    assert _doc_count(TestSession) == 0


def test_fr_doc_001_batch_requires_doc_admin(client, seed, auth):
    seed({"qe": ["QUALITY_EVALUATOR"], "aud": ["AUDITOR"]})
    for user in ("qe", "aud"):
        assert _batch(client, auth, [("a.txt", b"a")], user=user).status_code == 403
