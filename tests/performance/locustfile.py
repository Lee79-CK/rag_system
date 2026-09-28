"""부하 테스트 (PRD §8.5, §25.5) — 질문 Burst/Peak/Soak (Web Chat).

실행 예:
  # 질문 Burst: 50명, 10초 — ACK(질문 Post + placeholder 생성) p95 ≤ 2s
  CHAT_EMAIL=hong@example.com CHAT_PASSWORD='Rag!Assistant2026' \\
  locust -f tests/performance/locustfile.py --headless -u 50 -r 50 -t 10s \\
         --host http://localhost:8001
  # Peak: 동시 10~15 답변 생성 (스트리밍 완료 p95 ≤ 30s 는 llm.stream.end 관측으로 별도 측정)

환경변수:
  CHAT_EMAIL / CHAT_PASSWORD — 테스트 계정 (scripts/create_chat_user.py 로 생성)
  CHAT_CHANNEL                — 질문할 채널 name (기본 rag-cloud-ops)
  CHAT_WORKSPACE_SLUG         — prehash salt (기본 rag)
  ※ 게이트웨이 rate limit(RATE_LIMIT_PER_USER_PER_MIN) 을 부하 시험 동안 충분히 올려 둘 것.
"""

from __future__ import annotations

import os
import time
import uuid

from locust import HttpUser, between, events, task
from rag_common.passwords import compute_prehash

_EMAIL = os.environ.get("CHAT_EMAIL", "hong@example.com")
_PASSWORD = os.environ.get("CHAT_PASSWORD", "Rag!Assistant2026")
_CHANNEL = os.environ.get("CHAT_CHANNEL", "rag-cloud-ops")
_SLUG = os.environ.get("CHAT_WORKSPACE_SLUG", "rag")
_PREHASH = compute_prehash(_SLUG, _EMAIL, _PASSWORD)  # 600k PBKDF2 는 1회만

# ACK p95 목표 (§8.2)
ACK_P95_TARGET_MS = 2000


class ChatUser(HttpUser):
    """chat-web 사용자 행동(로그인 → 질문 POST)을 모사하여 gateway ACK 지연을 측정한다."""

    wait_time = between(0.1, 0.5)

    def on_start(self) -> None:
        r = self.client.post(
            "/api/v1/auth/login",
            json={
                "email": _EMAIL,
                "prehash": _PREHASH,
                "client_nonce": uuid.uuid4().hex,
                "timestamp": int(time.time() * 1000),
            },
            name="login",
        )
        r.raise_for_status()
        self.client.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
        self.channel_id = self.client.get(f"/api/v1/channels/{_CHANNEL}", name="channel").json()[
            "id"
        ]

    @task
    def ask(self) -> None:
        body = {
            "channel_id": self.channel_id,
            "message": "장애 등급별 대응 절차를 알려주세요.",
            "client_id": str(uuid.uuid4()),
        }
        with self.client.post(
            "/api/v1/posts", json=body, name="post_ack", catch_response=True
        ) as resp:
            if resp.status_code == 201:
                resp.success()
            else:
                resp.failure(f"status {resp.status_code}")


@events.quitting.add_listener
def _assert_ack_p95(environment, **_kwargs) -> None:
    """종료 시 ACK p95 목표 위반이면 종료코드 1 (CI gate)."""
    stats = environment.stats.get("post_ack", "POST") if environment.stats else None
    p95 = (stats or environment.stats.total).get_response_time_percentile(0.95)
    if p95 is not None and p95 > ACK_P95_TARGET_MS:
        print(f"[FAIL] ACK p95 {p95}ms > {ACK_P95_TARGET_MS}ms 목표")
        environment.process_exit_code = 1
    else:
        print(f"[OK] ACK p95 {p95}ms ≤ {ACK_P95_TARGET_MS}ms")
