"""답변 피드백(👍/👎) 수신 — Interactive Message Action (docs/TDD.md §7.1.4, v1.1).

MUST: LLM/RAG/Queue 미호출. context HMAC 서명 검증 필수. 응답은 ephemeral_text만.
"""

from __future__ import annotations

import hmac
import time
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import ORJSONResponse
from mattermost_adapter import feedback_signature
from pydantic import ValidationError
from rag_common import new_request_id
from rag_observability import bind_context, clear_context, get_logger
from rag_schemas import InteractiveActionRequest

from bridge import metrics
from bridge.api.responses import error_response
from bridge.core.config import Settings
from bridge.core.security import source_ip_allowed
from bridge.deps import provide_feedback_repo, provide_redis, provide_settings
from bridge.repos import FeedbackRepo
from bridge.services.rate_limit import allow

log = get_logger("bridge.actions")
router = APIRouter()

_THANKS_TEXT = "피드백이 반영되었습니다. 감사합니다 🙏"
_RATE_LIMIT_TEXT = "요청이 많아 잠시 후 다시 시도해 주세요."


def _ephemeral(text: str) -> ORJSONResponse:
    """클릭한 사용자에게만 표시되는 응답 (Channel 오염 없음, §7.1.4 step6)."""
    return ORJSONResponse(status_code=200, content={"ephemeral_text": text})


@router.post("/integrations/mattermost/v1/actions")
async def actions(
    request: Request,
    settings: Annotated[Settings, Depends(provide_settings)],
    redis: Annotated[Any, Depends(provide_redis)],
    feedback_repo: Annotated[FeedbackRepo, Depends(provide_feedback_repo)],
) -> ORJSONResponse:
    start = time.perf_counter()
    request_id = new_request_id()

    if not settings.feedback_enabled:
        return error_response(
            404, "FEEDBACK_DISABLED", "피드백 기능이 비활성화되어 있습니다.", request_id
        )

    # 1. Body → InteractiveActionRequest
    try:
        body = await request.json()
        req = InteractiveActionRequest.model_validate(body)
    except (ValidationError, ValueError, UnicodeDecodeError):
        return error_response(400, "INVALID_PAYLOAD", "요청 본문을 해석할 수 없습니다.", request_id)

    ctx = req.context
    bind_context(
        request_id=request_id,
        channel_id=req.channel_id,
        user_id=req.user_id,
        operation="feedback",
    )
    try:
        # 2. Source IP allowlist (Outgoing과 동일 CIDR)
        client_ip = request.client.host if request.client else ""
        if not source_ip_allowed(client_ip, settings.allowed_cidrs()):
            return error_response(
                403, "SOURCE_NOT_ALLOWED", "허용되지 않은 출처입니다.", request_id
            )

        # 3. HMAC 서명 검증 — 서명 키가 비어 있으면(Secret 미마운트) 전부 거부 (fail-closed)
        signing_key = settings.feedback_signing_key()
        if not signing_key:
            metrics.bridge_invalid_feedback_sig_total.inc()
            log.error("actions.signing_key_missing")
            return error_response(401, "INVALID_SIGNATURE", "서명이 유효하지 않습니다.", request_id)
        expected_sig = feedback_signature(signing_key, ctx.message_id, ctx.value)
        if not hmac.compare_digest(ctx.sig, expected_sig):
            metrics.bridge_invalid_feedback_sig_total.inc()
            log.warning("actions.invalid_signature")
            return error_response(401, "INVALID_SIGNATURE", "서명이 유효하지 않습니다.", request_id)

        # 4. message 존재 + channel 일치 검증 (서명 유효해도 반드시 확인, §7.1.4 MUST)
        if not feedback_repo.message_exists_in_channel(ctx.message_id, req.channel_id):
            if feedback_repo.message_exists(ctx.message_id):
                log.warning("actions.channel_mismatch")
                return error_response(
                    403,
                    "FEEDBACK_CHANNEL_MISMATCH",
                    "다른 채널의 답변에는 피드백할 수 없습니다.",
                    request_id,
                )
            return error_response(
                404, "FEEDBACK_TARGET_NOT_FOUND", "대상 답변을 찾을 수 없습니다.", request_id
            )

        # 5. Rate Limit (사용자당 분당 20, 질문 Rate Limit과 별도 키)
        if not await allow(
            redis,
            f"fb:rl:user:{req.user_id}",
            settings.rate_limit_feedback_per_user_per_min,
        ):
            return _ephemeral(_RATE_LIMIT_TEXT)

        # 6. UPSERT (재클릭 = 의견 변경, 행 수 1 유지)
        feedback_repo.upsert_feedback(ctx.message_id, req.user_id, ctx.value, req.channel_id)

        metrics.feedback_received_total.labels(
            value=ctx.value.value.lower(), channel_id=req.channel_id
        ).inc()
        metrics.feedback_action_latency_seconds.observe(time.perf_counter() - start)
        log.info("actions.feedback_recorded", value=ctx.value.value)
        return _ephemeral(_THANKS_TEXT)
    finally:
        clear_context()
