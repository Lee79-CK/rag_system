"""오류 로그 화면의 파드 로그 조회 — kube-apiserver pods / pods/log (TDD §7.5).

보안 원칙
- 조회 대상은 **서버측 allowlist**(서비스명 → namespace·labelSelector)로만 정한다. 클라이언트가 임의의
  namespace/Pod 를 지정할 수 없다.
- 모든 줄에 `mask_text`(DSN 비밀번호·Bearer·JWT 서명·webhook) 적용 — rag-worker 의 RQ Traceback 처럼
  structlog 마스킹을 거치지 않은 stderr 원문도 있기 때문.
- 크기 상한(Pod 당 bytes·줄 수)으로 대량 로그가 응답·브라우저를 막지 않게 한다.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Protocol
from urllib.parse import quote

import httpx
from rag_observability import get_logger, mask_text

from admin.core.config import Settings, get_settings
from admin.services.k8s import KubeApi, safe_error

log = get_logger("admin.pod_logs")

MAX_BYTES_PER_POD = 512 * 1024
MAX_LINES_PER_POD = 2000
INDEX_JOB_LABEL = "ragplatform.io/index-job-id"


class PodLogsDisabled(RuntimeError):
    """POD_LOG_ACCESS=none — 화면은 DB 오류 목록만 제공."""


class PodLogsError(RuntimeError):
    """kube-apiserver 호출 실패. 메시지는 safe_error 문구만(토큰 비노출)."""


@dataclass
class PodInfo:
    name: str
    restart_count: int = 0
    phase: str | None = None


@dataclass
class LogLine:
    ts: str | None
    text: str


@dataclass
class PodLog:
    pod: str
    previous: bool
    lines: list[LogLine] = field(default_factory=list)
    truncated: bool = False


class PodLogReader(Protocol):
    def list_pods(self, namespace: str, label_selector: str) -> list[PodInfo]: ...

    def read_log(
        self, namespace: str, pod: str, *, since_time: dt.datetime, previous: bool = False
    ) -> str: ...


class DisabledPodLogReader:
    def list_pods(self, namespace: str, label_selector: str) -> list[PodInfo]:
        raise PodLogsDisabled()

    def read_log(self, namespace, pod, *, since_time, previous=False) -> str:  # noqa: ANN001
        raise PodLogsDisabled()


class K8sPodLogReader:
    """RBAC: 대상 namespace 의 pods get/list, pods/log get (chart rag-pod-log-reader Role)."""

    def __init__(self, api: KubeApi | None = None) -> None:
        self._api = api or KubeApi(timeout=10.0)

    def list_pods(self, namespace: str, label_selector: str) -> list[PodInfo]:
        try:
            resp = self._api.client.get(
                f"/api/v1/namespaces/{namespace}/pods",
                params={"labelSelector": label_selector},
                headers=self._api.headers(),
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise PodLogsError(f"pods 조회 실패: {safe_error(exc)}") from exc
        pods = []
        for item in resp.json().get("items") or []:
            statuses = (item.get("status") or {}).get("containerStatuses") or []
            pods.append(
                PodInfo(
                    name=item["metadata"]["name"],
                    restart_count=sum(int(c.get("restartCount") or 0) for c in statuses),
                    phase=(item.get("status") or {}).get("phase"),
                )
            )
        return pods

    def read_log(
        self, namespace: str, pod: str, *, since_time: dt.datetime, previous: bool = False
    ) -> str:
        params = {
            "timestamps": "true",
            "sinceTime": since_time.astimezone(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "limitBytes": str(MAX_BYTES_PER_POD),
        }
        if previous:
            params["previous"] = "true"
        try:
            resp = self._api.client.get(
                f"/api/v1/namespaces/{namespace}/pods/{quote(pod)}/log",
                params=params,
                headers=self._api.headers(accept="text/plain"),
            )
            if previous and resp.status_code == 400:
                return ""  # 이전 컨테이너 없음
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise PodLogsError(f"pods/log 조회 실패: {safe_error(exc)}") from exc
        return resp.text


def log_targets(settings: Settings) -> dict[str, tuple[str, str]]:
    """서비스명 → (namespace, labelSelector). parser-indexer 는 index_job_id 라벨로 별도 조립."""
    app, ai = settings.log_app_namespace, settings.log_ai_namespace
    targets = {
        svc: (app, f"app.kubernetes.io/name={svc}")
        for svc in ("rag-worker", "rag-api", "chat-gateway", "admin-api")
    }
    targets |= {
        svc: (ai, f"app.kubernetes.io/name={svc}") for svc in ("embedding-api", "reranker-api")
    }
    targets["vllm"] = (ai, "app.kubernetes.io/name=vllm")
    targets["parser-indexer"] = (
        settings.index_job_namespace,
        "app.kubernetes.io/name=parser-indexer",
    )
    return targets


def _parse_ts(prefix: str) -> dt.datetime | None:
    # "2026-10-10T02:58:11.123456789Z" — 나노초는 마이크로초로 자른다
    try:
        head, _, frac = prefix.rstrip("Z").partition(".")
        base = dt.datetime.fromisoformat(head).replace(tzinfo=dt.UTC)
        return base + dt.timedelta(microseconds=int((frac + "000000")[:6])) if frac else base
    except ValueError:
        return None


def collect_logs(
    reader: PodLogReader,
    namespace: str,
    label_selector: str,
    *,
    since: dt.datetime,
    until: dt.datetime,
) -> list[PodLog]:
    """대상 Pod 들의 [since, until] 로그(재시작 Pod 는 이전 컨테이너 포함). 줄마다 마스킹."""
    out: list[PodLog] = []
    for pod in reader.list_pods(namespace, label_selector):
        for previous in (True, False) if pod.restart_count else (False,):
            raw = reader.read_log(namespace, pod.name, since_time=since, previous=previous)
            if previous and not raw:
                continue
            entry = PodLog(pod=pod.name, previous=previous)
            for line in raw.splitlines():
                ts_raw, _, text = line.partition(" ")
                ts = _parse_ts(ts_raw)
                if ts is None:  # timestamp 없는 줄(이어진 줄) — 원문 유지
                    ts_raw, text = "", line
                elif ts > until:
                    break
                if len(entry.lines) >= MAX_LINES_PER_POD:
                    entry.truncated = True
                    break
                entry.lines.append(LogLine(ts=ts_raw or None, text=mask_text(text)))
            if len(raw.encode("utf-8")) >= MAX_BYTES_PER_POD:
                entry.truncated = True
            out.append(entry)
    return out


def build_reader(settings: Settings) -> PodLogReader:
    if settings.pod_log_access.lower() == "k8s":
        return K8sPodLogReader()
    return DisabledPodLogReader()


@lru_cache
def get_pod_log_reader() -> PodLogReader:
    return build_reader(get_settings())


def provide_pod_log_reader() -> PodLogReader:
    """FastAPI 의존성 — 테스트는 dependency_overrides 로 fake 를 주입한다."""
    return get_pod_log_reader()
