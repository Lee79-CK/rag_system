"""색인 Job 트리거 — docs/TDD.md §7.5 (ADR-008, FR-IDX-010).

admin-api 는 `index_jobs` 행을 만든 뒤 parser-indexer 를 **K8s Job 으로 인스턴스화**한다.
추가 의존성 없이 in-cluster ServiceAccount 토큰 + httpx 로 kube-apiserver 를 직접 호출한다:

1. GET  /api/v1/namespaces/{ns}/configmaps/{template}   → `job.yaml` (chart 가 렌더한 Job 스펙)
2. `__INDEX_JOB_ID__` 치환
3. POST /apis/batch/v1/namespaces/{ns}/jobs  (Content-Type: application/yaml)

`INDEX_JOB_TRIGGER=none`(기본) 이면 NoopTrigger — 로컬/테스트에서는 CLI 로 직접 실행한다
(`python -m ingestion.main --index-job-id <uuid>`). 외부 네트워크 호출은 없다(클러스터 내부 API 만).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Protocol

import httpx
from rag_observability import get_logger

from admin.core.config import Settings, get_settings

log = get_logger("admin.index_trigger")

_SA_DIR = Path("/var/run/secrets/kubernetes.io/serviceaccount")
_PLACEHOLDER = "__INDEX_JOB_ID__"


class IndexTriggerError(RuntimeError):
    """Job 생성 실패. 호출자는 index_jobs.error 에 기록하고 202 는 유지한다(수동 실행 가능)."""


class IndexJobTrigger(Protocol):
    name: str

    def trigger(self, index_job_id: str) -> str | None:
        """Job 을 생성하고 생성된 Job 이름(또는 None)을 반환한다."""
        ...


class NoopTrigger:
    """트리거 없음 — index_jobs 행만 신호로 남긴다 (로컬/CLI 실행)."""

    name = "none"

    def trigger(self, index_job_id: str) -> str | None:
        log.info("index_trigger.noop", index_job_id=index_job_id)
        return None


class K8sJobTrigger:
    """kube-apiserver 직접 호출 (ServiceAccount 토큰). RBAC: configmaps get, jobs create."""

    name = "k8s"

    def __init__(
        self,
        *,
        namespace: str,
        template_configmap: str,
        api_base: str | None = None,
        token: str | None = None,
        ca_path: str | None = None,
        client: httpx.Client | None = None,
        timeout: float = 5.0,
    ) -> None:
        self._ns = namespace
        self._cm = template_configmap
        self._api_base = api_base or _in_cluster_api_base()
        self._token = token if token is not None else _read(_SA_DIR / "token")
        verify: str | bool = ca_path or (
            str(_SA_DIR / "ca.crt") if (_SA_DIR / "ca.crt").is_file() else True
        )
        self._client = client or httpx.Client(
            base_url=self._api_base, timeout=timeout, verify=verify
        )

    def _headers(self, content_type: str | None = None) -> dict[str, str]:
        h = {"Authorization": f"Bearer {self._token}", "Accept": "application/json"}
        if content_type:
            h["Content-Type"] = content_type
        return h

    def _load_template(self) -> str:
        url = f"/api/v1/namespaces/{self._ns}/configmaps/{self._cm}"
        try:
            resp = self._client.get(url, headers=self._headers())
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise IndexTriggerError(f"configmap {self._cm} 조회 실패: {_safe(exc)}") from exc
        data = resp.json().get("data") or {}
        template = data.get("job.yaml")
        if not template or _PLACEHOLDER not in template:
            raise IndexTriggerError(f"configmap {self._cm} 에 job.yaml/{_PLACEHOLDER} 가 없습니다")
        return template

    def trigger(self, index_job_id: str) -> str | None:
        manifest = self._load_template().replace(_PLACEHOLDER, index_job_id)
        url = f"/apis/batch/v1/namespaces/{self._ns}/jobs"
        try:
            resp = self._client.post(
                url, content=manifest.encode("utf-8"), headers=self._headers("application/yaml")
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise IndexTriggerError(f"Job 생성 실패: {_safe(exc)}") from exc
        name = (resp.json().get("metadata") or {}).get("name")
        log.info("index_trigger.k8s_job_created", index_job_id=index_job_id, job_name=name)
        return name


def _safe(exc: httpx.HTTPError) -> str:
    """예외 메시지에서 상태코드/종류만 남긴다 (Bearer 토큰 등 헤더 노출 방지)."""
    status = getattr(getattr(exc, "response", None), "status_code", None)
    return f"{type(exc).__name__}" + (f" status={status}" if status else "")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip() if path.is_file() else ""


def _in_cluster_api_base() -> str:
    import os

    host = os.environ.get("KUBERNETES_SERVICE_HOST", "kubernetes.default.svc")
    port = os.environ.get("KUBERNETES_SERVICE_PORT", "443")
    return f"https://{host}:{port}"


def build_trigger(settings: Settings) -> IndexJobTrigger:
    mode = settings.index_job_trigger.lower()
    if mode == "k8s":
        return K8sJobTrigger(
            namespace=settings.index_job_namespace,
            template_configmap=settings.index_job_template_configmap,
        )
    if mode != "none":
        log.warning("index_trigger.unknown_mode", mode=mode)
    return NoopTrigger()


@lru_cache
def get_index_trigger() -> IndexJobTrigger:
    return build_trigger(get_settings())


def provide_index_trigger() -> IndexJobTrigger:
    """FastAPI 의존성 (테스트에서 dependency_overrides 로 교체)."""
    return get_index_trigger()
