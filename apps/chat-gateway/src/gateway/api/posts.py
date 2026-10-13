"""Post API — 질문 수신 파이프라인 (docs/TDD.md §7.1.1).

POST /api/v1/posts:
 1. 인증(JWT) + 채널 멤버십 (비멤버 404)
 2. 입력 검증 (길이, 답글의 답글 금지)
 3. client_id 중복 제거 (Redis NX) — FR-WEB-006
 4. Rate limit (user / channel)
 5. 트리거 판정 (binding, trigger word, loop guard)
 6. 질문 Post (+ placeholder Bot Post + chat_jobs) 단일 트랜잭션
 7. chat:req:{job} 보관 → RQ enqueue (실패 시 Job FAILED + Bot Post 오류 갱신)
 8. post.created emit → 201 + 질문 PostDto
"""

from __future__ import annotations

import time
from typing import Any

from chat_adapter import ERROR_TEXT, to_post_dto
from fastapi import APIRouter, Response
from rag_common import new_trace_id
from rag_observability import bind_context, get_logger
from rag_schemas import ChatRequest
from rag_schemas.webchat import (
    CreatePostRequest,
    PostDeleted,
    PostDto,
    ThreadDto,
    ThreadMeta,
)

from gateway.api.channels import permissions_for, require_member
from gateway.api.responses import ApiError
from gateway.core import dedup
from gateway.deps import AppSettings, CurrentUser, Emitter, QueueEnqueuer, Redis, Store
from gateway.metrics import (
    gateway_ack_latency_seconds,
    gateway_duplicate_post_total,
    gateway_post_received_total,
)
from gateway.services.rate_limit import allow
from gateway.services.trigger import resolve_trigger

router = APIRouter(prefix="/api/v1", tags=["posts"])
log = get_logger(__name__)

CHAT_REQUEST_TTL_SECONDS = 86400


@router.post("/posts", response_model=PostDto, status_code=201)
async def create_post(
    body: CreatePostRequest,
    user: CurrentUser,
    store: Store,
    redis: Redis,
    settings: AppSettings,
    enqueuer: QueueEnqueuer,
    emitter: Emitter,
) -> Any:
    started = time.perf_counter()
    trace_id = new_trace_id()
    bind_context(trace_id=trace_id, channel_id=body.channel_id)

    try:
        ch, _role = require_member(store, body.channel_id, user)
    except ApiError:
        gateway_post_received_total.labels("not_member").inc()
        raise
    message = body.message.strip()
    if not message or len(message) > settings.chat_max_post_chars:
        gateway_post_received_total.labels("invalid").inc()
        raise ApiError(400, "INVALID_MESSAGE", "메시지가 비어 있거나 너무 깁니다.")

    root = None
    if body.root_id:
        root = store.get_post(body.root_id)
        if root is None or root.channel_id != ch.id:
            raise ApiError(404, "POST_NOT_FOUND", "원본 메시지를 찾을 수 없습니다.")
        if root.root_id is not None:
            raise ApiError(400, "NESTED_REPLY", "답글에는 답글을 달 수 없습니다.")

    # 3. 중복 제거 — 같은 client_id 재전송은 기존 Post 반환 (새 Job 없음)
    if body.client_id:
        existing = await dedup.claim(redis, user.id, body.client_id)
        if existing is not None:
            gateway_duplicate_post_total.inc()
            gateway_post_received_total.labels("duplicate").inc()
            prev = store.get_post(existing) if existing != dedup.PENDING else None
            if prev is None:
                raise ApiError(409, "DUPLICATE_REQUEST", "이미 처리 중인 요청입니다.")
            return to_post_dto(prev)

    # 4. rate limit
    if not (
        await allow(redis, f"chat:rl:user:{user.id}", settings.rate_limit_per_user_per_min)
        and await allow(redis, f"chat:rl:chan:{ch.id}", settings.rate_limit_per_channel_per_min)
    ):
        if body.client_id:
            await dedup.release(redis, user.id, body.client_id)
        gateway_post_received_total.labels("rate_limited").inc()
        raise ApiError(429, "RATE_LIMITED", "요청이 많아 잠시 후 다시 시도해 주세요.")

    # 5. 트리거 판정
    binding = store.get_binding(ch.id)
    trigger = resolve_trigger(
        binding,
        message,
        root_id=root.id if root else None,
        author_is_bot=user.is_bot,
        default_trigger_word=settings.chat_default_trigger_word,
        thread_has_bot=store.thread_has_bot(root.id) if root else False,
    )
    bot = store.get_bot_user() if trigger else None

    # 6. 영속화
    try:
        if trigger and bot and binding:
            result = store.create_question(
                channel_id=ch.id,
                root_id=root.id if root else None,
                user=user,
                message=message,
                client_id=body.client_id,
                bot=bot,
                bot_root_id=trigger.bot_root_id,
                # 직접 대화는 문서 검색이 없으므로 "근거 문서를 찾는 중" 접수 안내 대신 "생각 중…"
                bot_props={
                    "streaming": True,
                    "ack": binding.ack_message_enabled and not trigger.direct,
                }
                | ({"direct": True} if trigger.direct else {}),
            )
        else:
            result = None
            user_post = store.create_post(
                channel_id=ch.id,
                root_id=root.id if root else None,
                user=user,
                message=message,
                client_id=body.client_id,
            )
    except Exception:
        if body.client_id:
            await dedup.release(redis, user.id, body.client_id)
        raise

    if result is None:
        if body.client_id:
            await dedup.resolve(redis, user.id, body.client_id, user_post.id)
        dto = to_post_dto(user_post)
        await emitter.post_created(dto)
        gateway_post_received_total.labels("posted_only").inc()
        gateway_ack_latency_seconds.observe(time.perf_counter() - started)
        return dto

    assert result.bot_post is not None and result.job_id is not None and trigger is not None
    if body.client_id:
        await dedup.resolve(redis, user.id, body.client_id, result.user_post.id)
    user_dto = to_post_dto(result.user_post)
    await emitter.post_created(user_dto)
    await emitter.post_created(to_post_dto(result.bot_post))

    # 7. Worker 전달 — 질문 원문은 Redis 에 TTL 로만 보관 (Job payload = job_id)
    chat_request = ChatRequest(
        source="web",
        channel_id=ch.id,
        user_id=user.id,
        user_name=user.display_name,
        post_id=result.user_post.id,
        root_id=root.id if root else None,
        bot_post_id=result.bot_post.id,
        message=trigger.question,
        trace_id=trace_id,
        direct=trigger.direct,
    )
    try:
        await redis.set(
            f"chat:req:{result.job_id}", chat_request.model_dump_json(), ex=CHAT_REQUEST_TTL_SECONDS
        )
        enqueuer(result.job_id)
    except Exception as exc:  # noqa: BLE001 — Queue 장애: 질문은 남기고 Bot Post 를 오류로
        log.error("enqueue_failed", error=type(exc).__name__, job_id=result.job_id)
        store.mark_job_failed(result.job_id, f"ENQUEUE_FAILED:{type(exc).__name__}")
        failed = store.update_post(
            result.bot_post.id, message=ERROR_TEXT, props={"streaming": False, "kind": "error"}
        )
        if failed:
            await emitter.post_updated(to_post_dto(failed))
        gateway_post_received_total.labels("enqueue_failed").inc()
        return user_dto

    gateway_post_received_total.labels("accepted").inc()
    gateway_ack_latency_seconds.observe(time.perf_counter() - started)
    log.info("question_accepted", job_id=result.job_id)
    return user_dto


@router.get("/posts/{post_id}/thread", response_model=ThreadDto)
async def get_thread(post_id: str, user: CurrentUser, store: Store) -> ThreadDto:
    root = store.get_post(post_id)
    if root is None:
        raise ApiError(404, "POST_NOT_FOUND", "메시지를 찾을 수 없습니다.")
    if root.root_id:  # 답글 id 로 들어오면 root 로 승격
        root = store.get_post(root.root_id) or root
    ch, role = require_member(store, root.channel_id, user)
    binding = store.get_binding(ch.id)
    replies = store.list_replies(root.id)
    return ThreadDto(
        root=to_post_dto(root),
        replies=[to_post_dto(r) for r in replies],
        thread=ThreadMeta(reply_count=len(replies), participant_count=len(root.participants)),
        me=permissions_for(role, user, bot_enabled=bool(binding and binding.enabled)),
    )


@router.delete("/posts/{post_id}", status_code=204)
async def delete_post(post_id: str, user: CurrentUser, store: Store, emitter: Emitter) -> Response:
    post = store.get_post(post_id)
    if post is None:
        raise ApiError(404, "POST_NOT_FOUND", "메시지를 찾을 수 없습니다.")
    _, role = require_member(store, post.channel_id, user)
    is_author = post.user is not None and post.user.id == user.id
    if not (is_author or permissions_for(role, user, bot_enabled=False).permissions["moderate"]):
        raise ApiError(403, "FORBIDDEN", "삭제 권한이 없습니다.")
    store.soft_delete_post(post.id)
    await emitter.post_deleted(
        PostDeleted(id=post.id, channel_id=post.channel_id, root_id=post.root_id)
    )
    return Response(status_code=204)
