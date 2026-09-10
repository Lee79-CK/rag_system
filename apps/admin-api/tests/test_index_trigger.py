"""K8sJobTrigger — kube-apiserver 호출 계약 (ADR-008, FR-IDX-010). 네트워크 없이 MockTransport 로 검증."""

from __future__ import annotations

import json

import httpx
import pytest
from admin.services.index_trigger import (
    IndexTriggerError,
    K8sJobTrigger,
    NoopTrigger,
    build_trigger,
)

TEMPLATE = """apiVersion: batch/v1
kind: Job
metadata:
  generateName: index-job-
  namespace: rag-ingestion
spec:
  template:
    spec:
      containers:
        - name: parser-indexer
          command: ["python", "-m", "ingestion.main", "--index-job-id", "__INDEX_JOB_ID__"]
"""


def _trigger(handler) -> K8sJobTrigger:
    client = httpx.Client(base_url="https://kube", transport=httpx.MockTransport(handler))
    return K8sJobTrigger(
        namespace="rag-ingestion",
        template_configmap="parser-indexer-job-template",
        api_base="https://kube",
        token="sa-token",
        client=client,
    )


def test_fr_idx_010_k8s_trigger_posts_job_manifest():
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.method == "GET":
            assert (
                request.url.path
                == "/api/v1/namespaces/rag-ingestion/configmaps/parser-indexer-job-template"
            )
            return httpx.Response(200, json={"data": {"job.yaml": TEMPLATE}})
        assert request.method == "POST"
        assert request.url.path == "/apis/batch/v1/namespaces/rag-ingestion/jobs"
        assert request.headers["content-type"] == "application/yaml"
        assert request.headers["authorization"] == "Bearer sa-token"
        body = request.content.decode()
        assert "__INDEX_JOB_ID__" not in body
        assert "--index-job-id" in body and "job-uuid-1" in body
        return httpx.Response(201, json={"metadata": {"name": "index-job-abc12"}})

    name = _trigger(handler).trigger("job-uuid-1")
    assert name == "index-job-abc12"
    assert [c.method for c in calls] == ["GET", "POST"]


def test_k8s_trigger_wraps_http_errors_without_leaking_token():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"message": "forbidden"})

    with pytest.raises(IndexTriggerError) as exc:
        _trigger(handler).trigger("job-uuid-2")
    assert "status=403" in str(exc.value)
    assert "sa-token" not in str(exc.value)


def test_k8s_trigger_rejects_template_without_placeholder():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": {"job.yaml": "kind: Job"}})

    with pytest.raises(IndexTriggerError):
        _trigger(handler).trigger("job-uuid-3")


def test_build_trigger_defaults_to_noop(monkeypatch):
    from admin.core.config import Settings

    assert isinstance(build_trigger(Settings()), NoopTrigger)
    assert build_trigger(Settings(INDEX_JOB_TRIGGER="none")).name == "none"  # type: ignore[call-arg]
    assert json.dumps({"ok": True})  # noqa: S101 — keep json import used for readability
