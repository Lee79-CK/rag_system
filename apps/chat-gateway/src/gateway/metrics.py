"""Prometheus 메트릭 (docs/TDD.md §12.1 — Gateway / Feedback 세트)."""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

# --- 질문 수신 파이프라인 ---
gateway_post_received_total = Counter(
    "gateway_post_received_total",
    "POST /api/v1/posts 처리 결과",
    ["result"],  # accepted|posted_only|not_member|duplicate|rate_limited|invalid|enqueue_failed
)

gateway_ack_latency_seconds = Histogram(
    "gateway_ack_latency_seconds",
    "질문 수신 → 응답(placeholder Bot Post 생성 포함)까지 지연 (p95 ≤ 2s 목표)",
)

gateway_duplicate_post_total = Counter(
    "gateway_duplicate_post_total",
    "중복 client_id 요청 횟수 (§7.1.1 step3, FR-WEB-006)",
)

# --- 인증 ---
gateway_login_total = Counter(
    "gateway_login_total",
    "로그인 시도 결과",
    ["result"],  # ok|invalid|rate_limited|replay
)

# --- 실시간 ---
gateway_ws_connections = Gauge(
    "gateway_ws_connections",
    "현재 socket.io 연결 수 (pod 단위)",
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

gateway_invalid_feedback_token_total = Counter(
    "gateway_invalid_feedback_token_total",
    "피드백 토큰(HMAC) 검증 실패 횟수 (§7.1.4)",
)
