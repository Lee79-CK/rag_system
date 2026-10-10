"""Chat Job 처리 (§7.2.1). RQ가 `rag.worker.chat_worker.run_chat_job`를 호출한다.

핵심 로직은 process_chat_job(deps, ...)로 분리하여 fake 주입 테스트가 가능하게 한다.
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
from typing import Any, Protocol

from rag_observability import get_logger
from rag_schemas import ChannelBinding, ChatRequest, RagCompletion, scope_key

from rag.domain.pipeline import RagPipeline

CHANNEL_DISABLED_TEXT = "⚠️ 이 채널의 RAG 응답이 비활성화되어 답변할 수 없습니다."

log = get_logger("rag.worker")


def _error_text(exc: BaseException) -> str:
    """chat_jobs.error 용 — 예외 종류·대상 URL 포함. httpx.ReadTimeout 처럼 메시지가 빈 예외도 원인이 남게."""
    text = str(exc) or "(no message)"
    url = None
    with contextlib.suppress(Exception):  # httpx 오류는 요청 URL 을 갖는다(없으면 RuntimeError)
        url = str(exc.request.url)  # type: ignore[attr-defined]
    out = f"{type(exc).__name__}: {text}"
    if url and url not in text:
        out += f" [{url}]"
    return out[:500]


class BindingReader(Protocol):
    def get_binding(self, channel_id: str) -> ChannelBinding | None: ...


class ConversationStore(Protocol):
    def upsert_conversation(
        self, *, scope_key: str, channel_id: str, root_id: str | None, mode: str
    ) -> str: ...

    def load_history(self, conversation_id: str, limit: int) -> list[tuple[str, str]]: ...

    def add_user_message(self, conversation_id: str, post_id: str, content: str) -> str: ...

    def add_assistant_message(
        self,
        conversation_id: str,
        content: str,
        *,
        post_id: str,
        latency_ms: int | None,
        citations: list[dict[str, Any]],
    ) -> str: ...

    def claim_job(self, job_id: str) -> bool:
        """QUEUED → RUNNING 원자 전이. 이미 다른 워커가 잡았거나 끝난 job 이면 False (멱등 가드)."""
        ...

    def update_job_status(
        self, job_id: str, status: str, *, error: str | None = ..., mark_started: bool = ...
    ) -> None: ...


class DeltaSink(Protocol):
    async def push(self, delta: str) -> None: ...

    async def flush(self) -> None: ...


class DeliveryPort(Protocol):
    """답변 전달 포트. 구현: rag.adapters.webchat_delivery.WebChatDelivery."""

    def open_stream(self, request: ChatRequest) -> DeltaSink: ...

    async def deliver_answer(
        self,
        *,
        binding: ChannelBinding,
        request: ChatRequest,
        completion: RagCompletion,
        chat_job_id: str,
    ) -> bool: ...

    async def deliver_error(self, *, request: ChatRequest, text: str = ...) -> bool: ...


@dataclass(slots=True)
class WorkerDeps:
    binding_reader: BindingReader
    store: ConversationStore
    pipeline: RagPipeline
    delivery: DeliveryPort


async def process_chat_job(
    deps: WorkerDeps, job_id: str, request: ChatRequest
) -> RagCompletion | None:
    """§7.2.1 1~15단계. 실패 시 Bot Post 를 오류 안내로 갱신 + job FAILED.

    RQ 재실행/중복 enqueue 로 같은 job 이 두 번 들어와도 Bot Post 스트리밍/최종 갱신이 중복되지 않도록
    QUEUED→RUNNING 전이를 원자적으로 선점(claim)한 워커만 진행한다. 선점 실패 시 None (Bot Post 미변경).
    """
    if not deps.store.claim_job(job_id):
        log.warning("worker.job_already_claimed", job_id=job_id)
        return None

    binding = deps.binding_reader.get_binding(request.channel_id)
    if binding is None or not binding.enabled:
        deps.store.update_job_status(job_id, "FAILED", error="CHANNEL_NOT_BOUND_OR_DISABLED")
        # placeholder Bot Post 가 "생각 중" 으로 남지 않도록 안내로 갱신한다.
        await deps.delivery.deliver_error(request=request, text=CHANNEL_DISABLED_TEXT)
        raise RuntimeError(f"binding missing/disabled for {request.channel_id}")

    # 2. scope_key → conversation upsert
    sk = scope_key(binding, request.root_id, request.post_id)
    conversation_id = deps.store.upsert_conversation(
        scope_key=sk,
        channel_id=request.channel_id,
        root_id=request.root_id,
        mode=binding.conversation_mode.value,
    )

    # 4. 대화 이력 로딩 (현재 질문 이전 turn만) — conversation_id로만 필터 (FR-CTX-002)
    history = deps.store.load_history(conversation_id, binding.history_turns * 2)

    # 3. user 메시지 저장
    deps.store.add_user_message(conversation_id, request.post_id, request.message)

    # 5~12. 파이프라인 (LLM 토큰 스트리밍 → llm.stream.delta)
    stream = deps.delivery.open_stream(request)
    try:
        output = await deps.pipeline.run(
            question=request.message, binding=binding, history=history, on_delta=stream.push
        )
        await stream.flush()
    except Exception as exc:  # noqa: BLE001 — 파이프라인 실패 시 오류 안내 (FR-CHAT-009)
        log.error("worker.pipeline_failed", job_id=job_id, error=_error_text(exc))
        deps.store.update_job_status(job_id, "FAILED", error=_error_text(exc))
        await deps.delivery.deliver_error(request=request)
        raise

    if output.usage.get("rerank_fallback"):
        log.warning(
            "worker.rerank_fallback",
            job_id=job_id,
            rerank_ms=output.usage.get("rerank_ms"),
            hint="reranker timeout/오류 → 벡터 순서로 답변. RERANKER_TIMEOUT·VECTOR_TOP_K·reranker 상태 확인",
        )
    latency_ms = int(output.usage.get("llm_ms", 0)) or None
    citation_dicts = [c.model_dump() for c in output.citations]
    message_id = deps.store.add_assistant_message(
        conversation_id,
        output.answer,
        post_id=request.bot_post_id,
        latency_ms=latency_ms,
        citations=citation_dicts,
    )

    completion = RagCompletion(
        message_id=message_id,
        answer=output.answer,
        citations=output.citations,
        insufficient_evidence=output.insufficient_evidence,
        usage=output.usage,
    )

    # 13~14. Bot Post 최종 갱신 + post.updated / llm.stream.end
    ok = await deps.delivery.deliver_answer(
        binding=binding, request=request, completion=completion, chat_job_id=job_id
    )

    # 15. Job 상태 확정
    deps.store.update_job_status(job_id, "COMPLETED" if ok else "DELIVERY_FAILED")
    return completion


_deps: WorkerDeps | None = None
_loop: asyncio.AbstractEventLoop | None = None


def _event_loop() -> asyncio.AbstractEventLoop:
    """프로세스 수명 동안 재사용하는 event loop.

    AsyncRedisManager(socket.io)·httpx·AsyncOpenAI 클라이언트는 생성된 loop 에 묶이므로,
    job 마다 asyncio.run() 으로 loop 를 새로 만들면 SimpleWorker 에서 연결 재사용이 깨진다.
    """
    global _loop
    if _loop is None or _loop.is_closed():
        _loop = asyncio.new_event_loop()
    return _loop


def get_worker_deps() -> WorkerDeps:
    """RQ Worker 프로세스 startup 시 실 어댑터로 1회 구성 (lazy singleton)."""
    global _deps
    if _deps is None:
        from rag.worker.bootstrap import build_worker_deps

        _deps = build_worker_deps()
    return _deps


def load_chat_request(job_id: str) -> ChatRequest:
    """chat-gateway 가 Redis `chat:req:{job_id}`에 보관한 ChatRequest를 로딩한다 (§7.1.1).

    질문 원문은 chat_posts 에도 있으나, 트리거 제거·정규화된 표준 요청은 Redis 에서 읽는다.
    """
    import redis

    from rag.core.config import get_settings

    # job 마다 연결을 열고 반드시 닫는다 (장기 실행 RQ 워커의 소켓 누수 방지)
    with redis.Redis.from_url(get_settings().redis_url) as conn:
        raw = conn.get(f"chat:req:{job_id}")
    if raw is None:
        raise RuntimeError(f"chat request payload missing for job {job_id}")
    return ChatRequest.model_validate_json(raw)


def run_chat_job(job_id: str) -> None:
    """RQ entrypoint. gateway 는 job_id만 enqueue하고 ChatRequest는 Redis에 보관한다 (§7.1.1)."""
    request = load_chat_request(job_id)
    _event_loop().run_until_complete(process_chat_job(get_worker_deps(), job_id, request))
