"""부하 테스트 (PRD §8.5, §25.5) — Webhook Burst/Peak/Soak.

실행 예:
  # Webhook Burst: 50명, 10초 — ACK p95 ≤ 2s
  locust -f tests/performance/locustfile.py --headless -u 50 -r 50 -t 10s \
         --host http://localhost:8001
  # Peak: 동시 10~15 답변 생성 (게시 p95 ≤ 30s는 Worker/게시 관측으로 별도 측정)

환경변수:
  MM_OUTGOING_TOKEN  — Outgoing Webhook Token (없으면 임의 값)
"""

from __future__ import annotations

import os
import time

from locust import HttpUser, between, events, task

_TOKEN = os.environ.get("MM_OUTGOING_TOKEN", "dev-token")

# ACK p95 목표 (§8.2)
ACK_P95_TARGET_MS = 2000


class WebhookUser(HttpUser):
    """Mattermost Outgoing Webhook을 모사하여 Bridge ACK 지연을 측정한다."""

    wait_time = between(0.1, 0.5)

    @task
    def outgoing(self) -> None:
        post_id = f"perf-{time.time_ns()}"
        payload = {
            "token": _TOKEN,
            "team_id": "team-001",
            "team_domain": "cloud-team",
            "channel_id": "channel-001",
            "channel_name": "rag-cloud-ops",
            "user_id": "perf-user",
            "user_name": "perf",
            "post_id": post_id,
            "root_id": "",
            "text": "장애 등급별 대응 절차를 알려주세요.",
        }
        with self.client.post(
            "/integrations/mattermost/v1/outgoing",
            json=payload,
            name="outgoing_ack",
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"status {resp.status_code}")


@events.quitting.add_listener
def _assert_ack_p95(environment, **_kwargs) -> None:
    """종료 시 ACK p95 목표 위반이면 종료코드 1 (CI gate)."""
    stats = environment.stats.total
    p95 = stats.get_response_time_percentile(0.95)
    if p95 is not None and p95 > ACK_P95_TARGET_MS:
        print(f"[FAIL] ACK p95 {p95}ms > {ACK_P95_TARGET_MS}ms 목표")
        environment.process_exit_code = 1
    else:
        print(f"[OK] ACK p95 {p95}ms ≤ {ACK_P95_TARGET_MS}ms")
