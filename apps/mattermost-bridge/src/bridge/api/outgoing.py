"""Outgoing Webhook 수신 파이프라인 (docs/TDD.md §7.1.1 step1-10).

무시성 이벤트(disabled/loop/trigger-miss/duplicate/rate-limited)는 반드시 HTTP 200
(보안 위반 401/403 제외) — §3.3 note. LLM/RAG 호출은 절대 없다 (§7.1.1 MUST, §12.6).
"""

from __future__ import annotations

import time
from typing import Annotated, Any
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, Request
from fastapi.responses import ORJSONResponse
from mattermost_adapter import normalize_outgoing_payload
from pydantic import ValidationError
from rag_common import TTLCache, new_request_id, new_trace_id, sha256_hex
from rag_observability import bind_context, clear_context, get_logger
from rag_schemas import ChannelBinding, ChannelMode

from bridge import metrics
from bridge.api.responses import error_response, ignore_response, text_response
from bridge.core.config import Settings
from bridge.core.dedup import delete_dedup, is_duplicate
from bridge.core.loop_guard import is_loop_message
from bridge.core.security import constant_time_token_check, source_ip_allowed
from bridge.deps import (
    provide_binding_cache,
    provide_binding_repo,
    provide_enqueuer,
    provide_event_repo,
    provide_redis,
    provide_settings,
)
from bridge.repos import BindingRepo, EventRepo
from bridge.services.event_normalizer import to_chat_request
from bridge.services.job_enqueuer import Enqueuer
from bridge.services.rate_limit import allow

log = get_logger("bridge.outgoing")
router = APIRouter()

_CHAT_REQUEST_TTL_SECONDS = 86400  # Worker가 로딩하기 전까지 ChatRequest 보관 (24h)

_ACK_TEXT = "질문을 접수했습니다. 답변을 준비 중입니다."
_DISABLED_TEXT = "이 채널은 현재 RAG 어시스턴트가 비활성화되어 있습니다. 관리자에게 문의해 주세요."
_RATE_LIMIT_TEXT = "요청이 많아 잠시 후 다시 시도해 주세요."


async def _read_payload_dict(request: Request) -> dict[str, Any]:
    """Content-Type 판별 → dict (§7.1.1 step1). urlencoded는 직접 파싱한다."""
    ctype = request.headers.get("content-type", "")
    if "application/x-www-form-urlencoded" in ctype:
        body = await request.body()
        parsed = parse_qs(body.decode("utf-8"))
        return {k: v[0] for k, v in parsed.items() if v}
    # 기본: JSON (multipart는 사용하지 않음)
    return await request.json()


@router.post("/integrations/mattermost/v1/outgoing")
async def outgoing(
    request: Request,
    settings: Annotated[Settings, Depends(provide_settings)],
    redis: Annotated[Any, Depends(provide_redis)],
    binding_repo: Annotated[BindingRepo, Depends(provide_binding_repo)],
    event_repo: Annotated[EventRepo, Depends(provide_event_repo)],
    enqueuer: Annotated[Enqueuer, Depends(provide_enqueuer)],
    binding_cache: Annotated[TTLCache[str, ChannelBinding], Depends(provide_binding_cache)],
) -> ORJSONResponse:
    start = time.perf_counter()
    request_id = new_request_id()
    trace_id = new_trace_id()

    # 1. Content-Type 판별 → 정규화
    try:
        raw = await _read_payload_dict(request)
        payload = normalize_outgoing_payload(raw)
    except (ValidationError, ValueError, UnicodeDecodeError):
        return error_response(400, "INVALID_PAYLOAD", "요청 본문을 해석할 수 없습니다.", request_id)

    bind_context(
        request_id=request_id,
        trace_id=trace_id,
        team_id=payload.team_id,
        channel_id=payload.channel_id,
        user_id=payload.user_id,
        mattermost_post_id=payload.post_id,
        operation="outgoing",
    )
    try:
        # 2. Token 검증 (상수시간)
        if not constant_time_token_check(
            payload.token.get_secret_value(), settings.outgoing_token()
        ):
            metrics.bridge_webhook_received_total.labels(result="invalid_token").inc()
            metrics.bridge_invalid_token_total.inc()
            log.warning("outgoing.invalid_token")
            return error_response(
                401, "INVALID_TOKEN", "인증 토큰이 유효하지 않습니다.", request_id
            )

        # 3. Source IP allowlist
        client_ip = request.client.host if request.client else ""
        if not source_ip_allowed(client_ip, settings.allowed_cidrs()):
            metrics.bridge_webhook_received_total.labels(result="source_not_allowed").inc()
            log.warning("outgoing.source_not_allowed")
            return error_response(
                403, "SOURCE_NOT_ALLOWED", "허용되지 않은 출처입니다.", request_id
            )

        # 4. Channel Binding 조회 (캐시 60s → PG fallback)
        cache_key = f"{payload.team_id}:{payload.channel_id}"
        binding = binding_cache.get(cache_key)
        if binding is None:
            binding = binding_repo.get_binding(payload.team_id, payload.channel_id)
            if binding is not None:
                binding_cache.set(cache_key, binding)
        if binding is None:
            metrics.bridge_webhook_received_total.labels(result="not_bound").inc()
            log.warning("outgoing.channel_not_bound")  # CH-005 보안 로그
            return error_response(403, "CHANNEL_NOT_BOUND", "등록되지 않은 채널입니다.", request_id)
        if not binding.enabled:
            metrics.bridge_webhook_received_total.labels(result="disabled").inc()
            return text_response(_DISABLED_TEXT)

        # 5. Loop Guard
        if is_loop_message(payload.user_name, settings.bridge_bot_username):
            metrics.bridge_webhook_received_total.labels(result="loop").inc()
            log.info("outgoing.loop_ignored")
            return ignore_response()

        # 6. Trigger 처리 (TRIGGER_WORD 모드)
        if binding.mode == ChannelMode.TRIGGER_WORD:
            trigger = binding.trigger_word or settings.mattermost_default_trigger_word
            if not payload.text.lstrip().startswith(trigger):
                metrics.bridge_webhook_received_total.labels(result="trigger_miss").inc()
                return ignore_response()

        # 7. Dedup (Redis SET NX)
        if await is_duplicate(redis, payload.post_id):
            metrics.bridge_webhook_received_total.labels(result="duplicate").inc()
            metrics.bridge_duplicate_event_total.inc()
            log.info("outgoing.duplicate_ignored")
            return ignore_response()

        # 7.5 Rate Limit (§10 — step7 이후, 고정 윈도우)
        user_ok = await allow(
            redis, f"mm:rl:user:{payload.user_id}", settings.rate_limit_per_user_per_min
        )
        chan_ok = await allow(
            redis, f"mm:rl:chan:{payload.channel_id}", settings.rate_limit_per_channel_per_min
        )
        if not (user_ok and chan_ok):
            metrics.bridge_webhook_received_total.labels(result="rate_limited").inc()
            return text_response(_RATE_LIMIT_TEXT)

        # 8. mattermost_events + chat_jobs INSERT (단일 트랜잭션, 실패 시 dedup 롤백)
        payload_hash = sha256_hex(f"{payload.post_id}:{payload.text}")  # 원문 미저장 (NFR-DATA-007)
        try:
            _event_id, job_id = event_repo.record_event_and_job(
                post_id=payload.post_id,
                root_id=payload.root_id or None,
                team_id=payload.team_id,
                channel_id=payload.channel_id,
                user_id=payload.user_id,
                payload_hash=payload_hash,
            )
        except Exception:
            await delete_dedup(redis, payload.post_id)  # 재시도 허용 (§7.1.1 step8 MUST)
            log.exception("outgoing.persist_failed")
            return error_response(
                500, "INTERNAL_ERROR", "요청 처리 중 오류가 발생했습니다.", request_id
            )

        # ChatRequest 를 Worker가 로딩할 수 있도록 Redis에 보관 (Mattermost 종속성 제거 완료본)
        chat_request = to_chat_request(payload, binding, trace_id)
        await redis.set(
            f"chat:req:{job_id}", chat_request.model_dump_json(), ex=_CHAT_REQUEST_TTL_SECONDS
        )

        # 9. RQ enqueue
        try:
            enqueuer(job_id)
        except Exception:
            log.exception("outgoing.enqueue_failed")
            return error_response(500, "INTERNAL_ERROR", "작업 등록에 실패했습니다.", request_id)

        # 10. 200 반환
        metrics.bridge_webhook_received_total.labels(result="accepted").inc()
        metrics.bridge_ack_latency_seconds.observe(time.perf_counter() - start)
        log.info("outgoing.accepted", job_id=job_id)
        if binding.ack_message_enabled:
            return text_response(_ACK_TEXT)
        return ignore_response()
    finally:
        clear_context()
