"""감사 로그 조회 API 테스트 — FR-AUTH-005 ("누가/언제/무엇을 수행했는지 조회 가능")."""

from __future__ import annotations

import datetime as dt

from admin.db.models import AuditLog


def _add(
    TestSession, actor: str, action: str, *, result="OK", minutes_ago=0, detail=None, target=None
):
    with TestSession() as s:
        row = AuditLog(
            actor=actor,
            action=action,
            target=target if target is not None else action.partition(" ")[2] or None,
            result=result,
            detail=detail,
            ts=dt.datetime.now(dt.UTC) - dt.timedelta(minutes=minutes_ago),
        )
        s.add(row)
        s.commit()
        return str(row.id)


def test_fr_auth_005_mutation_is_visible_in_audit_log_api(client, seed, auth):
    """미들웨어가 기록한 변경 요청이 조회 API 로 다시 보인다(행위자·Method·Path·상태)."""
    seed({"docadmin": ["DOC_ADMIN"], "auditor": ["AUDITOR"]})
    resp = client.post(
        "/api/v1/documents",
        files={"file": ("audit.txt", b"audit-body", "text/plain")},
        headers=auth("docadmin"),
    )
    assert resp.status_code == 201, resp.text

    logs = client.get("/api/v1/audit-logs", headers=auth("auditor"))
    assert logs.status_code == 200, logs.text
    row = next(r for r in logs.json()["data"] if r["path"] == "/api/v1/documents")
    assert row["actor"] == "docadmin"
    assert row["method"] == "POST"
    assert row["status_code"] == 201
    assert row["result"] == "OK"
    assert row["created_at"]


def test_fr_auth_005_list_orders_desc_and_parses_views(client, seed, auth, TestSession):
    seed({"admin": ["SYS_ADMIN"]})
    old = _add(
        TestSession, "kim", "PUT /api/v1/settings/x", minutes_ago=60, detail={"status_code": 200}
    )
    acl = _add(
        TestSession,
        "hong",
        "DOCUMENT_ACL_UPDATE",
        target="doc-1",
        minutes_ago=5,
        detail={"before": [], "after": ["c1"]},
    )
    new = _add(
        TestSession,
        "hong",
        "DELETE /api/v1/documents/abc",
        result="ERROR",
        detail={"status_code": 409},
    )

    data = client.get("/api/v1/audit-logs", headers=auth("admin")).json()
    ids = [r["id"] for r in data["data"]]
    assert ids.index(new) < ids.index(acl) < ids.index(old)  # 최신순
    by_id = {r["id"]: r for r in data["data"]}
    assert by_id[new]["method"] == "DELETE" and by_id[new]["path"] == "/api/v1/documents/abc"
    assert by_id[new]["status_code"] == 409 and by_id[new]["result"] == "ERROR"
    # 핸들러가 직접 남긴 행은 method/path 없이 action·detail 그대로
    assert by_id[acl]["method"] is None and by_id[acl]["path"] is None
    assert by_id[acl]["action"] == "DOCUMENT_ACL_UPDATE"
    assert by_id[acl]["detail"] == {"before": [], "after": ["c1"]}
    assert data["meta"]["truncated"] is False


def test_fr_auth_005_filters(client, seed, auth, TestSession):
    seed({"admin": ["SYS_ADMIN"]})
    a = _add(TestSession, "Hong.Gildong", "POST /api/v1/chat/channels", minutes_ago=120)
    b = _add(TestSession, "kim", "DELETE /api/v1/documents/abc", result="DENIED", minutes_ago=30)
    c = _add(TestSession, "kim", "ERROR_LOG_VIEW", target="reranker-api", minutes_ago=1)

    def ids(query: str) -> set[str]:
        resp = client.get(f"/api/v1/audit-logs?{query}", headers=auth("admin"))
        assert resp.status_code == 200, resp.text
        return {r["id"] for r in resp.json()["data"]}

    assert ids("actor=hong") == {a}  # 부분 일치, 대소문자 무시
    assert ids("action=documents") == {b}  # Path 부분 일치
    assert ids("action=reranker") == {c}  # target 도 검색
    assert ids("action=error_log") == {c}
    assert ids("method=delete") == {b}
    assert ids("result=DENIED") == {b}
    since = (dt.datetime.now(dt.UTC) - dt.timedelta(minutes=60)).isoformat()
    assert ids(f"from={since.replace('+', '%2B')}") == {b, c}
    until = (dt.datetime.now(dt.UTC) - dt.timedelta(minutes=10)).isoformat()
    assert ids(f"to={until.replace('+', '%2B')}") == {a, b}


def test_fr_auth_005_invalid_filters_422(client, seed, auth):
    seed({"admin": ["SYS_ADMIN"]})
    for query, code in (
        ("method=GET", "INVALID_METHOD"),
        ("result=MAYBE", "INVALID_RESULT"),
        ("from=2026-10-10T10:00:00Z&to=2026-10-10T09:00:00Z", "INVALID_RANGE"),
    ):
        resp = client.get(f"/api/v1/audit-logs?{query}", headers=auth("admin"))
        assert resp.status_code == 422, query
        assert resp.json()["error"]["code"] == code


def test_fr_auth_005_limit_reports_truncation(client, seed, auth, TestSession):
    seed({"admin": ["SYS_ADMIN"]})
    for i in range(3):
        _add(TestSession, "kim", f"POST /api/v1/x/{i}", minutes_ago=i)
    data = client.get("/api/v1/audit-logs?limit=2", headers=auth("admin")).json()
    assert len(data["data"]) == 2
    assert data["meta"]["truncated"] is True and data["meta"]["limit"] == 2


def test_fr_auth_005_audit_logs_require_sys_admin_or_auditor(client, seed, auth):
    seed(
        {
            "admin": ["SYS_ADMIN"],
            "auditor": ["AUDITOR"],
            "doc": ["DOC_ADMIN"],
            "qe": ["QUALITY_EVALUATOR"],
        }
    )
    assert client.get("/api/v1/audit-logs", headers=auth("admin")).status_code == 200
    assert client.get("/api/v1/audit-logs", headers=auth("auditor")).status_code == 200
    assert client.get("/api/v1/audit-logs", headers=auth("doc")).status_code == 403
    assert client.get("/api/v1/audit-logs", headers=auth("qe")).status_code == 403
