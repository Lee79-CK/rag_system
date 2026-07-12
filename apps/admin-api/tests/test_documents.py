"""문서 업로드/중복 테스트 — FR-DOC-002/003."""

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
