"""RBAC / 인증 테스트 — §7.5, §22.5."""

from __future__ import annotations


def test_rbac_forbidden_without_role(client, seed, auth):
    # AUDITOR만 있는 사용자는 문서 업로드(SYS_ADMIN/DOC_ADMIN 필요) 불가.
    seed({"auditor": ["AUDITOR"]})
    resp = client.post(
        "/api/v1/documents",
        files={"file": ("a.txt", b"data", "text/plain")},
        headers=auth("auditor"),
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["error"]["code"] == "FORBIDDEN"


def test_unauthenticated_rejected(client, seed, auth):
    seed({"sysadmin": ["SYS_ADMIN"]})
    # X-Auth-User 헤더 없음 → 401.
    resp = client.get("/api/v1/settings")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "UNAUTHENTICATED"


def test_unknown_user_rejected(client, seed, auth):
    seed({"sysadmin": ["SYS_ADMIN"]})
    resp = client.get("/api/v1/settings", headers=auth("ghost"))
    assert resp.status_code == 401


def test_whoami_returns_roles(client, seed, auth):
    seed({"sysadmin": ["SYS_ADMIN", "AUDITOR"]})
    resp = client.get("/api/v1/auth/whoami", headers=auth("sysadmin"))
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["login_id"] == "sysadmin"
    assert set(data["roles"]) == {"SYS_ADMIN", "AUDITOR"}


def test_audit_log_written_on_mutation(client, TestSession, seed, auth):
    from admin.db.models import AuditLog

    seed({"sysadmin": ["SYS_ADMIN"]})
    client.put(
        "/api/v1/settings/similarity_threshold",
        json={"value": 0.35},
        headers=auth("sysadmin"),
    )
    with TestSession() as s:
        logs = s.query(AuditLog).all()
        assert any(log.action.startswith("PUT") and log.actor == "sysadmin" for log in logs)


def test_health_endpoints(client):
    assert client.get("/health/live").status_code == 200
    assert client.get("/health/startup").status_code == 200
    ready = client.get("/health/ready")
    assert ready.status_code == 200
    assert ready.json()["db"] is True
    metrics = client.get("/metrics")
    assert metrics.status_code == 200


def test_chat_jobs_readable_by_quality_evaluator(client, seed, auth):
    """대화 작업(실패 Job 점검)은 SYS_ADMIN·QUALITY_EVALUATOR — admin-web 사이드바와 같은 역할."""
    seed({"qe": ["QUALITY_EVALUATOR"], "docadmin": ["DOC_ADMIN"]})
    assert client.get("/api/v1/chat-jobs", headers=auth("qe")).status_code == 200
    assert client.get("/api/v1/chat-jobs", headers=auth("docadmin")).status_code == 403
