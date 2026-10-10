"""문서 원본 다운로드·미리보기, 색인 텍스트(청크) 조회 — FR-DOC-010 (원본과 파싱 결과 확인)."""

from __future__ import annotations

import uuid
from urllib.parse import quote

from admin.db.models import AuditLog, DocumentVersion


def _upload(client, auth, name: str, body: bytes, mime: str = "application/octet-stream") -> str:
    resp = client.post(
        "/api/v1/documents",
        files={"file": (name, body, mime)},
        headers=auth("docadmin"),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]["document"]["id"]


def _audit_actions(TestSession, doc_id: str) -> list[str]:
    with TestSession() as s:
        return [r.action for r in s.query(AuditLog).filter_by(target=doc_id).order_by(AuditLog.ts)]


def _version(TestSession, doc_id: str) -> DocumentVersion:
    with TestSession() as s:
        return s.query(DocumentVersion).filter_by(document_id=uuid.UUID(doc_id)).one()


class _FakeIndex:
    def __init__(self, rows=None, fail: bool = False) -> None:
        self.rows = rows or []
        self.fail = fail
        self.calls: list[str] = []

    def deactivate_document(self, document_id):
        pass

    def list_chunks(self, document_version_id):
        from admin.services.search_index import SearchIndexError

        self.calls.append(document_version_id)
        if self.fail:
            raise SearchIndexError("ConnectError: qdrant down")
        return self.rows


def _index(client, **kw) -> _FakeIndex:
    from admin.services.search_index import provide_search_index

    fake = _FakeIndex(**kw)
    client.app.dependency_overrides[provide_search_index] = lambda: fake
    return fake


def test_fr_doc_010_download_returns_original_bytes_and_korean_filename(
    client, seed, auth, TestSession
):
    seed({"docadmin": ["DOC_ADMIN"]})
    body = b"%PDF-1.4 fake pdf bytes \x00\x01"
    doc_id = _upload(client, auth, "영화 수익 Top 100.pdf", body, "application/pdf")

    resp = client.get(f"/api/v1/documents/{doc_id}/file", headers=auth("docadmin"))
    assert resp.status_code == 200, resp.text
    assert resp.content == body
    assert resp.headers["content-type"] == "application/pdf"
    cd = resp.headers["content-disposition"]
    assert cd.startswith("attachment;")
    assert f"filename*=UTF-8''{quote('영화 수익 Top 100.pdf')}" in cd
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert _audit_actions(TestSession, doc_id)[-1] == "DOCUMENT_DOWNLOAD"

    by_version = client.get(f"/api/v1/documents/{doc_id}/file?version=1", headers=auth("docadmin"))
    assert by_version.status_code == 200 and by_version.content == body


def test_fr_doc_010_inline_preview_only_for_safe_types(client, seed, auth, TestSession):
    seed({"docadmin": ["DOC_ADMIN"]})
    pdf = _upload(client, auth, "a.pdf", b"%PDF-1.4 a", "application/pdf")
    txt = _upload(client, auth, "b.txt", "본문".encode(), "text/plain")
    html = _upload(client, auth, "c.html", b"<script>alert(1)</script>", "text/html")
    docx = _upload(client, auth, "d.docx", b"PK\x03\x04docx")

    def get(doc_id):
        return client.get(
            f"/api/v1/documents/{doc_id}/file?disposition=inline", headers=auth("docadmin")
        )

    assert get(pdf).headers["content-disposition"].startswith("inline;")
    r = get(txt)
    assert r.headers["content-disposition"].startswith("inline;")
    assert r.headers["content-type"] == "text/plain; charset=utf-8"
    # 업로드된 HTML 이 관리 화면 origin 에서 실행되면 안 된다 → inline 요청이어도 attachment
    assert get(html).headers["content-disposition"].startswith("attachment;")
    assert get(docx).headers["content-disposition"].startswith("attachment;")
    assert _audit_actions(TestSession, pdf)[-1] == "DOCUMENT_VIEW"
    assert _audit_actions(TestSession, html)[-1] == "DOCUMENT_DOWNLOAD"


def test_fr_doc_010_file_path_outside_storage_rejected(client, seed, auth, TestSession, tmp_path):
    seed({"docadmin": ["DOC_ADMIN"]})
    doc_id = _upload(client, auth, "e.txt", b"inside")
    outside = tmp_path / "secret.txt"
    outside.write_text("do not serve")
    with TestSession() as s:
        v = s.query(DocumentVersion).filter_by(document_id=uuid.UUID(doc_id)).one()
        v.file_path = str(outside)
        s.commit()

    resp = client.get(f"/api/v1/documents/{doc_id}/file", headers=auth("docadmin"))
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "FILE_NOT_FOUND"


def test_fr_doc_010_missing_file_and_version_404(client, seed, auth, TestSession):
    from pathlib import Path

    seed({"docadmin": ["DOC_ADMIN"]})
    doc_id = _upload(client, auth, "f.txt", b"to be removed")
    Path(_version(TestSession, doc_id).file_path).unlink()

    gone = client.get(f"/api/v1/documents/{doc_id}/file", headers=auth("docadmin"))
    assert gone.status_code == 404 and gone.json()["error"]["code"] == "FILE_NOT_FOUND"

    no_ver = client.get(f"/api/v1/documents/{doc_id}/file?version=9", headers=auth("docadmin"))
    assert no_ver.status_code == 404 and no_ver.json()["error"]["code"] == "VERSION_NOT_FOUND"

    no_doc = client.get(f"/api/v1/documents/{uuid.uuid4()}/file", headers=auth("docadmin"))
    assert no_doc.status_code == 404


def test_fr_doc_010_chunks_sorted_from_search_index(client, seed, auth, TestSession):
    seed({"docadmin": ["DOC_ADMIN"]})
    doc_id = _upload(client, auth, "g.txt", b"chunks")
    version_id = str(_version(TestSession, doc_id).id)
    fake = _index(
        client,
        rows=[
            {"chunk_index": 2, "page_start": 3, "page_end": 3, "text": "셋", "is_active": True},
            {"chunk_index": 0, "page_start": 1, "page_end": 1, "section": "1장", "text": "하나"},
            {"chunk_index": 1, "page_start": 1, "page_end": 2, "text": "둘", "is_active": True},
        ],
    )

    resp = client.get(f"/api/v1/documents/{doc_id}/chunks", headers=auth("docadmin"))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert fake.calls == [version_id]  # 활성 버전의 document_version_id 로만 조회
    assert [c["text"] for c in body["data"]] == ["하나", "둘", "셋"]
    assert body["data"][0]["section"] == "1장" and body["data"][0]["is_active"] is True
    assert body["meta"] == {"version": 1, "count": 3, "document_status": "UPLOADED"}
    assert _audit_actions(TestSession, doc_id)[-1] == "DOCUMENT_CONTENT_VIEW"


def test_fr_doc_010_chunks_search_index_down_503(client, seed, auth):
    seed({"docadmin": ["DOC_ADMIN"]})
    doc_id = _upload(client, auth, "h.txt", b"down")
    _index(client, fail=True)
    resp = client.get(f"/api/v1/documents/{doc_id}/chunks", headers=auth("docadmin"))
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "SEARCH_INDEX_UNAVAILABLE"


def test_fr_doc_010_content_requires_doc_admin(client, seed, auth):
    seed({"docadmin": ["DOC_ADMIN"], "qe": ["QUALITY_EVALUATOR"], "aud": ["AUDITOR"]})
    doc_id = _upload(client, auth, "i.txt", b"rbac")
    for user in ("qe", "aud"):
        for path in ("file", "chunks"):
            resp = client.get(f"/api/v1/documents/{doc_id}/{path}", headers=auth(user))
            assert resp.status_code == 403, (user, path)


def test_fr_doc_010_qdrant_list_chunks_pages_by_version(monkeypatch):
    """QdrantSearchIndex.list_chunks — document_version_id 필터로 scroll 페이지를 끝까지 읽는다."""
    import sys
    import types

    from admin.services.search_index import QdrantSearchIndex

    calls: list[dict] = []

    class _Point:
        def __init__(self, i):
            self.payload = {"chunk_index": i, "text": f"t{i}"}

    class _Client:
        def __init__(self, url, timeout):
            pass

        def scroll(self, **kw):
            calls.append(kw)
            if kw["offset"] is None:
                return [_Point(0), _Point(1)], "next"
            return [_Point(2)], None

        def close(self):
            pass

    from qdrant_client import models

    fake_mod = types.SimpleNamespace(QdrantClient=_Client, models=models)
    monkeypatch.setitem(sys.modules, "qdrant_client", fake_mod)

    rows = QdrantSearchIndex("http://q", "rag_chunks_v1", 5).list_chunks("ver-1")
    assert [r["chunk_index"] for r in rows] == [0, 1, 2]
    assert len(calls) == 2 and calls[1]["offset"] == "next"
    cond = calls[0]["scroll_filter"].must[0]
    assert cond.key == "document_version_id" and cond.match.value == "ver-1"
    assert calls[0]["with_vectors"] is False
