"""Widget Action — 답변 피드백 (docs/TDD.md §7.1.4, v1.1).

POST /api/v1/actions {post_id, block_id:"fb", action_id:"feedback:up|down", value:<feedback_token>}

동기 처리. **LLM/Queue 호출 금지** (CLAUDE.md Hard rule). 검증 순서:
 1. 피드백 기능 on (전역)       → 아니면 404 FEEDBACK_DISABLED
 2. JWT 인증                    → 401
 3. action_id 허용 목록         → 400 UNSUPPORTED_ACTION
 4. Bot Post 존재 + 채널 멤버   → 404 (비멤버도 동일 응답)
 5. Post → 답변 message 역조회  → 404 FEEDBACK_TARGET_NOT_FOUND
 6. HMAC 토큰(message_id:post_id) 상수시간 비교 → 401 INVALID_SIGNATURE
 7. 답변 채널 == Post 채널      → 403 FEEDBACK_CHANNEL_MISMATCH
 8. rate limit                  → 429
 9. upsert (재클릭 = 의견 변경) → props.feedback 집계 갱신 + post.updated
"""

from __future__ import annotations

import time
from typing import Any

from chat_adapter import to_post_dto, verify_feedback_token
from fastapi import APIRouter
from rag_observability import get_logger
from rag_schemas import (
    FEEDBACK_ACTION_DOWN,
    FEEDBACK_ACTION_UP,
    FeedbackValue,
    WidgetActionRequest,
)

from gateway.api.channels import require_member
from gateway.api.responses import ApiError
from gateway.deps import AppSettings, CurrentUser, Emitter, Redis, Store
from gateway.metrics import (
    feedback_action_latency_seconds,
    feedback_received_total,
    gateway_invalid_feedback_token_total,
)
from gateway.services.rate_limit import allow

router = APIRouter(prefix="/api/v1", tags=["actions"])
log = get_logger(__name__)

_ACTIONS = {FEEDBACK_ACTION_UP: FeedbackValue.UP, FEEDBACK_ACTION_DOWN: FeedbackValue.DOWN}


@router.post("/actions")
async def widget_action(
    body: WidgetActionRequest,
    user: CurrentUser,
    store: Store,
    redis: Redis,
    settings: AppSettings,
    emitter: Emitter,
) -> dict[str, Any]:
    started = time.perf_counter()
    if not settings.feedback_enabled:
        raise ApiError(404, "FEEDBACK_DISABLED", "피드백 기능이 비활성화되어 있습니다.")
    value = _ACTIONS.get(body.action_id)
    if value is None:
        raise ApiError(400, "UNSUPPORTED_ACTION", "지원하지 않는 액션입니다.")

    post = store.get_post(body.post_id)
    if post is None or post.type != "bot":
        raise ApiError(404, "FEEDBACK_TARGET_NOT_FOUND", "피드백 대상을 찾을 수 없습니다.")
    require_member(store, post.channel_id, user)

    ref = store.get_answer_ref(post.id)
    if ref is None:
        raise ApiError(404, "FEEDBACK_TARGET_NOT_FOUND", "피드백 대상을 찾을 수 없습니다.")

    if not verify_feedback_token(
        settings.feedback_signing_key(), ref.message_id, post.id, body.value or ""
    ):
        gateway_invalid_feedback_token_total.inc()
        raise ApiError(401, "INVALID_SIGNATURE", "서명이 유효하지 않습니다.")

    if ref.channel_id != post.channel_id:
        raise ApiError(403, "FEEDBACK_CHANNEL_MISMATCH", "다른 채널의 답변입니다.")

    if not await allow(
        redis, f"fb:rl:user:{user.id}", settings.rate_limit_feedback_per_user_per_min
    ):
        raise ApiError(429, "RATE_LIMITED", "잠시 후 다시 시도해 주세요.")

    store.upsert_feedback(ref.message_id, user.id, value, post.channel_id)
    counts = store.feedback_counts(ref.message_id)
    updated = store.update_post(post.id, props={"feedback": counts})
    if updated is not None:
        await emitter.post_updated(to_post_dto(updated))

    feedback_received_total.labels(value.value.lower(), post.channel_id).inc()
    feedback_action_latency_seconds.observe(time.perf_counter() - started)
    return {"ok": True, "feedback": counts}
