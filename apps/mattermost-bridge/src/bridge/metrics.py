"""Prometheus 메트릭 (docs/TDD.md §12.1 — Bridge / Feedback 세트)."""

from __future__ import annotations

from prometheus_client import Counter, Histogram

# --- Outgoing 수신 파이프라인 ---
bridge_webhook_received_total = Counter(
    "bridge_webhook_received_total",
    "Outgoing webhook 처리 결과 카운트",
    [
        "result"
    ],  # accepted|invalid_token|source_not_allowed|not_bound|disabled|loop|trigger_miss|duplicate|rate_limited
)

bridge_ack_latency_seconds = Histogram(
    "bridge_ack_latency_seconds",
    "Outgoing 동기 ACK 응답까지 지연 (p95 ≤ 2s 목표)",
)

bridge_invalid_token_total = Counter(
    "bridge_invalid_token_total",
    "Outgoing Token 불일치 횟수 (§7.1.1 step2)",
)

bridge_duplicate_event_total = Counter(
    "bridge_duplicate_event_total",
    "중복 post_id 이벤트 횟수 (§7.1.1 step7, FR-MM-006)",
)

# --- 피드백 (v1.1) ---
feedback_received_total = Counter(
    "feedback_received_total",
    "수신한 답변 피드백 (§7.1.4)",
    ["value", "channel_id"],  # value=up|down
)

feedback_action_latency_seconds = Histogram(
    "feedback_action_latency_seconds",
    "피드백 action 동기 처리 지연 (p95 ≤ 500ms 목표)",
)

bridge_invalid_feedback_sig_total = Counter(
    "bridge_invalid_feedback_sig_total",
    "피드백 context HMAC 서명 검증 실패 횟수 (§7.1.4 step3)",
)
