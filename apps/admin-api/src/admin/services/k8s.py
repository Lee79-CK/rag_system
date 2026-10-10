"""kube-apiserver 공통 접근 — in-cluster ServiceAccount 토큰 + httpx (추가 의존성 없음).

색인 Job 트리거(index_trigger)와 파드 로그 조회(pod_logs)가 공유한다.
- 토큰은 **요청마다** 파일에서 다시 읽는다 — projected SA 토큰은 주기적으로 회전하므로 프로세스 수명 동안
  캐시하면 만료 후 401 이 난다.
- 오류 문구는 `safe_error` 로 종류·상태코드만 남긴다(Authorization 헤더 등 토큰 노출 방지).
"""

from __future__ import annotations

import os
from pathlib import Path

import httpx

SA_DIR = Path("/var/run/secrets/kubernetes.io/serviceaccount")


def safe_error(exc: httpx.HTTPError) -> str:
    """예외 메시지에서 상태코드/종류만 남긴다 (Bearer 토큰 등 헤더 노출 방지)."""
    status = getattr(getattr(exc, "response", None), "status_code", None)
    return f"{type(exc).__name__}" + (f" status={status}" if status else "")


def read_file(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip() if path.is_file() else ""


def in_cluster_api_base() -> str:
    host = os.environ.get("KUBERNETES_SERVICE_HOST", "kubernetes.default.svc")
    port = os.environ.get("KUBERNETES_SERVICE_PORT", "443")
    return f"https://{host}:{port}"


class KubeApi:
    """base_url·CA 검증이 설정된 httpx 클라이언트 + 요청별 Bearer 헤더."""

    def __init__(
        self,
        *,
        api_base: str | None = None,
        token: str | None = None,
        ca_path: str | None = None,
        client: httpx.Client | None = None,
        timeout: float = 5.0,
    ) -> None:
        self._fixed_token = token  # 테스트 주입용. None 이면 SA 토큰 파일을 매번 읽는다
        verify: str | bool = ca_path or (
            str(SA_DIR / "ca.crt") if (SA_DIR / "ca.crt").is_file() else True
        )
        self.client = client or httpx.Client(
            base_url=api_base or in_cluster_api_base(), timeout=timeout, verify=verify
        )

    def headers(self, content_type: str | None = None, accept: str = "application/json") -> dict:
        token = self._fixed_token if self._fixed_token is not None else read_file(SA_DIR / "token")
        h = {"Authorization": f"Bearer {token}", "Accept": accept}
        if content_type:
            h["Content-Type"] = content_type
        return h
