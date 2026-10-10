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
from typing import Protocol

import httpx
from rag_observability import get_logger

from admin.core.config import Settings, get_settings
from admin.services.k8s import KubeApi, safe_error

log = get_logger("admin.index_trigger")

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
        self._api = KubeApi(
            api_base=api_base, token=token, ca_path=ca_path, client=client, timeout=timeout
        )
        self._client = self._api.client

    def _headers(self, content_type: str | None = None) -> dict[str, str]:
        return self._api.headers(content_type)

    def _load_template(self) -> str:
        url = f"/api/v1/namespaces/{self._ns}/configmaps/{self._cm}"
        try:
            resp = self._client.get(url, headers=self._headers())
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise IndexTriggerError(f"configmap {self._cm} 조회 실패: {safe_error(exc)}") from exc
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
            raise IndexTriggerError(f"Job 생성 실패: {safe_error(exc)}") from exc
        name = (resp.json().get("metadata") or {}).get("name")
        log.info("index_trigger.k8s_job_created", index_job_id=index_job_id, job_name=name)
        return name


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
