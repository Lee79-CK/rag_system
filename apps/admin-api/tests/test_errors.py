"""오류 로그 API — FR-OPS-011 (DB 오류 통합 목록 + 관련 파드 로그, SYS_ADMIN 전용)."""

from __future__ import annotations

import datetime as dt

import httpx
import pytest

NOW = dt.datetime.now(dt.UTC)


def _seed_errors(TestSession) -> dict:
    from admin.db.models import (
        AuditLog,
        ChatChannel,
        ChatJob,
        ChatPost,
        Document,
        DocumentVersion,
        IndexJob,
    )

    with TestSession() as s:
        ch = ChatChannel(name="ai-regulation", display_name="AI 규제")
        s.add(ch)
        s.flush()
        post = ChatPost(
            channel_id=ch.id, type="user", message="안전신뢰문서는 얼마나 보관하나요?\n상세히"
        )
        s.add(post)
        s.flush()
        chat_failed = ChatJob(
            post_id=post.id,
            status="FAILED",
            error="ReadTimeout: (no message) [http://reranker-api.rag-ai:8005/internal/v1/rerank]",
            queued_at=NOW - dt.timedelta(minutes=10),
        )
        chat_ok = ChatJob(post_id=post.id, status="COMPLETED", queued_at=NOW)
        doc = Document(title="4._260122_AI_business_responsibility_guideline-1")
        s.add_all([chat_failed, chat_ok, doc])
        s.flush()
        ver = DocumentVersion(
            document_id=doc.id,
            version=1,
            hash="sha256:x",
            file_path="x",
            file_size=1,
            status="ACTIVE",
        )
        s.add(ver)
        s.flush()
        idx_failed = IndexJob(
            document_version_id=ver.id, status="FAILED", stage="EMBEDDING", error="ReadTimeout"
        )
        idx_trigger = IndexJob(
            document_version_id=ver.id, status="PENDING", error="TRIGGER_FAILED[k8s]: 403"
        )
        idx_cancel = IndexJob(
            document_version_id=ver.id, status="CANCELLED", error="SUPERSEDED: 새 색인 요청"
        )
        s.add_all(
            [
                idx_failed,
                idx_trigger,
                idx_cancel,
                AuditLog(
                    actor="cklee",
                    action="POST /api/v1/documents",
                    target="/x",
                    result="ERROR",
                    detail={"status_code": 500},
                ),
                AuditLog(
                    actor="docadmin",
                    action="POST /api/v1/chat/channels",
                    target="/x",
                    result="DENIED",
                    detail={"status_code": 403},
                ),
                AuditLog(
                    actor="cklee",
                    action="GET x",
                    target="/x",
                    result="OK",
                    detail={"status_code": 200},
                ),
            ]
        )
        s.commit()
        return {"chat": str(chat_failed.id), "index": str(idx_failed.id)}


def test_fr_ops_011_errors_list_merges_chat_index_admin(client, seed, auth, TestSession):
    seed({"sysadmin": ["SYS_ADMIN"]})
    ids = _seed_errors(TestSession)
    resp = client.get("/api/v1/errors", headers=auth("sysadmin"))
    assert resp.status_code == 200, resp.text
    items = resp.json()["data"]
    by_source: dict[str, list[dict]] = {}
    for i in items:
        by_source.setdefault(i["source"], []).append(i)

    (chat,) = by_source["chat"]  # COMPLETED 제외
    assert chat["ref_id"] == ids["chat"]
    assert chat["summary"].startswith("#ai-regulation · 안전신뢰문서는")
    assert "\n" not in chat["summary"]
    assert chat["service"] == "reranker-api"  # error 의 URL 로 추정

    assert {i["status"] for i in by_source["index"]} == {"FAILED", "PENDING"}  # CANCELLED 제외
    assert all(i["service"] == "parser-indexer" for i in by_source["index"])
    assert {i["status"] for i in by_source["admin"]} == {"ERROR", "DENIED"}  # OK 제외
    assert "reranker-api" in resp.json()["meta"]["services"]

    only_chat = client.get("/api/v1/errors", params={"source": "chat"}, headers=auth("sysadmin"))
    assert {i["source"] for i in only_chat.json()["data"]} == {"chat"}
    bad = client.get("/api/v1/errors", params={"source": "x"}, headers=auth("sysadmin"))
    assert bad.status_code == 422


def test_fr_ops_011_errors_require_sys_admin(client, seed, auth):
    seed({"docadmin": ["DOC_ADMIN"], "qe": ["QUALITY_EVALUATOR"], "auditor": ["AUDITOR"]})
    for who in ("docadmin", "qe", "auditor"):
        assert client.get("/api/v1/errors", headers=auth(who)).status_code == 403
        r = client.get(
            "/api/v1/errors/logs",
            params={"service": "rag-worker", "at": NOW.isoformat()},
            headers=auth(who),
        )
        assert r.status_code == 403


class _FakeReader:
    def __init__(
        self, logs: dict[tuple[str, bool], str], restarts: int = 0, no_pods: bool = False
    ) -> None:
        self.logs = logs
        self.restarts = restarts
        self.no_pods = no_pods
        self.calls: list[tuple] = []

    def list_pods(self, namespace, label_selector):
        from admin.services.pod_logs import PodInfo

        self.calls.append(("list", namespace, label_selector))
        if self.no_pods:
            return []
        return [PodInfo(name="rag-worker-abc", restart_count=self.restarts)]

    def read_log(self, namespace, pod, *, since_time, previous=False):
        self.calls.append(("log", namespace, pod, since_time, previous))
        return self.logs.get((pod, previous), "")


def _reader(client, reader) -> None:
    from admin.services.pod_logs import provide_pod_log_reader

    client.app.dependency_overrides[provide_pod_log_reader] = lambda: reader


def test_fr_ops_011_pod_logs_window_masking_and_audit(client, seed, auth, TestSession):
    """allowlist 서비스만, [at-before, at+after] 절단, 줄마다 마스킹(RQ Traceback 은 structlog 마스킹 밖), 열람 감사."""
    from admin.db.models import AuditLog

    at = dt.datetime(2026, 10, 10, 2, 58, 11, tzinfo=dt.UTC)
    raw = "\n".join(
        [
            "2026-10-10T02:58:10.123456789Z Traceback (most recent call last):",
            "2026-10-10T02:58:10.223456789Z httpx.ReadTimeout",
            "2026-10-10T02:58:10.323456789Z connect postgresql+psycopg://rag:s3cret@pg:5432/rag",
            "2026-10-10T02:58:10.423456789Z Authorization: Bearer abc.def.ghi",
            "2026-10-10T03:30:00.000000000Z after-window line",
        ]
    )
    reader = _FakeReader(
        {("rag-worker-abc", False): raw, ("rag-worker-abc", True): "2026-10-10T02:57:00Z prev"},
        restarts=1,
    )
    _reader(client, reader)
    seed({"sysadmin": ["SYS_ADMIN"]})

    resp = client.get(
        "/api/v1/errors/logs",
        params={"service": "rag-worker", "at": at.isoformat(), "before_min": 5, "after_min": 2},
        headers=auth("sysadmin"),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["namespace"] == "rag-app"
    assert reader.calls[0] == ("list", "rag-app", "app.kubernetes.io/name=rag-worker")
    since = [c for c in reader.calls if c[0] == "log"][0][3]
    assert since == at - dt.timedelta(minutes=5)

    prev, cur = data["pods"]  # 재시작 Pod 는 이전 컨테이너 로그도
    assert prev["previous"] is True and cur["previous"] is False
    texts = [ln["text"] for ln in cur["lines"]]
    assert texts[0].startswith("Traceback")
    assert "s3cret" not in " ".join(texts) and "abc.def.ghi" not in " ".join(texts)
    assert "after-window line" not in texts
    with TestSession() as s:
        audit = s.query(AuditLog).filter_by(action="ERROR_LOG_VIEW").one()
    assert audit.actor == "sysadmin" and audit.target == "rag-worker"


def test_fr_ops_011_pod_logs_allowlist_and_index_job_selector(client, seed, auth):
    import uuid

    reader = _FakeReader({}, no_pods=True)  # 색인 Job Pod 는 TTL 1h 후 사라진다
    _reader(client, reader)
    seed({"sysadmin": ["SYS_ADMIN"]})
    at = NOW.isoformat()

    unknown = client.get(
        "/api/v1/errors/logs",
        params={"service": "kube-apiserver", "at": at},
        headers=auth("sysadmin"),
    )
    assert unknown.status_code == 422 and unknown.json()["error"]["code"] == "UNKNOWN_SERVICE"
    no_id = client.get(
        "/api/v1/errors/logs",
        params={"service": "parser-indexer", "at": at},
        headers=auth("sysadmin"),
    )
    assert no_id.status_code == 422

    jid = uuid.uuid4()
    ok = client.get(
        "/api/v1/errors/logs",
        params={"service": "parser-indexer", "at": at, "index_job_id": str(jid)},
        headers=auth("sysadmin"),
    )
    assert ok.status_code == 200
    assert reader.calls[0] == ("list", "rag-ingestion", f"ragplatform.io/index-job-id={jid}")
    assert "1시간" in ok.json()["data"]["reason"]  # Pod 없음 안내


def test_fr_ops_011_pod_logs_disabled_503(client, seed, auth):
    from admin.services.pod_logs import DisabledPodLogReader

    _reader(client, DisabledPodLogReader())
    seed({"sysadmin": ["SYS_ADMIN"]})
    r = client.get(
        "/api/v1/errors/logs",
        params={"service": "rag-worker", "at": NOW.isoformat()},
        headers=auth("sysadmin"),
    )
    assert r.status_code == 503 and r.json()["error"]["code"] == "POD_LOGS_DISABLED"


# ----- K8sPodLogReader (kube-apiserver 호출) -----


def _k8s_reader(handler):
    from admin.services.k8s import KubeApi
    from admin.services.pod_logs import K8sPodLogReader

    client = httpx.Client(base_url="https://kube", transport=httpx.MockTransport(handler))
    return K8sPodLogReader(KubeApi(api_base="https://kube", token="sa-token", client=client))


def test_fr_ops_011_k8s_reader_params_and_restart_count():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        assert request.headers["authorization"] == "Bearer sa-token"
        if request.url.path.endswith("/pods"):
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "metadata": {"name": "rag-worker-1"},
                            "status": {
                                "phase": "Running",
                                "containerStatuses": [{"restartCount": 2}],
                            },
                        }
                    ]
                },
            )
        return httpx.Response(200, text="2026-10-10T02:58:10Z line")

    reader = _k8s_reader(handler)
    (pod,) = reader.list_pods("rag-app", "app.kubernetes.io/name=rag-worker")
    assert pod.name == "rag-worker-1" and pod.restart_count == 2
    text = reader.read_log(
        "rag-app", "rag-worker-1", since_time=dt.datetime(2026, 10, 10, 2, 53, tzinfo=dt.UTC)
    )
    assert text.endswith("line")
    q = seen[1].url.params
    assert seen[0].url.params["labelSelector"] == "app.kubernetes.io/name=rag-worker"
    assert seen[1].url.path == "/api/v1/namespaces/rag-app/pods/rag-worker-1/log"
    assert q["timestamps"] == "true" and q["sinceTime"] == "2026-10-10T02:53:00Z"
    assert int(q["limitBytes"]) == 512 * 1024


def test_fr_ops_011_k8s_reader_error_does_not_leak_token():
    from admin.services.pod_logs import PodLogsError

    reader = _k8s_reader(lambda r: httpx.Response(403, json={"reason": "Forbidden"}))
    with pytest.raises(PodLogsError) as exc:
        reader.list_pods("rag-app", "x=y")
    assert "status=403" in str(exc.value) and "sa-token" not in str(exc.value)
