"""Chat Job 처리 (§7.2.1). RQ가 `rag.worker.chat_worker.run_chat_job`를 호출한다.

핵심 로직은 process_chat_job(deps, ...)로 분리하여 fake 주입 테스트가 가능하게 한다.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Protocol

from rag_schemas import ChannelBinding, ChatRequest, RagCompletion, scope_key

from rag.adapters.delivery_adapter import MattermostDelivery
from rag.domain.pipeline import RagPipeline
from rag.domain.prompt import INSUFFICIENT_EVIDENCE_TEXT


class BindingReader(Protocol):
    def get_binding(self, team_id: str, channel_id: str) -> ChannelBinding | None: ...


class ConversationStore(Protocol):
    def upsert_conversation(
        self, *, scope_key: str, team_id: str, channel_id: str, root_id: str | None, mode: str
    ) -> str: ...

    def load_history(self, conversation_id: str, limit: int) -> list[tuple[str, str]]: ...

    def add_user_message(self, conversation_id: str, post_id: str, content: str) -> str: ...

    def add_assistant_message(
        self,
        conversation_id: str,
        content: str,
        *,
        latency_ms: int | None,
        citations: list[dict[str, Any]],
    ) -> str: ...

    def update_job_status(
        self, job_id: str, status: str, *, error: str | None = ..., mark_started: bool = ...
    ) -> None: ...

    def record_delivery(
        self, job_id: str, channel_id: str, *, attempt: int, status: str, http_status: int | None
    ) -> None: ...


@dataclass(slots=True)
class WorkerDeps:
    binding_reader: BindingReader
    store: ConversationStore
    pipeline: RagPipeline
    delivery: MattermostDelivery


async def process_chat_job(deps: WorkerDeps, job_id: str, request: ChatRequest) -> RagCompletion:
    """§7.2.1 1~15단계. 실패 시 오류 Post 게시 + job FAILED."""
    deps.store.update_job_status(job_id, "RUNNING", mark_started=True)

    binding = deps.binding_reader.get_binding(request.team_id, request.channel_id)
    if binding is None or not binding.enabled:
        deps.store.update_job_status(job_id, "FAILED", error="CHANNEL_NOT_BOUND_OR_DISABLED")
        raise RuntimeError(f"binding missing/disabled for {request.channel_id}")

    # 2. scope_key → conversation upsert
    sk = scope_key(binding, request.root_id, request.post_id)
    conversation_id = deps.store.upsert_conversation(
        scope_key=sk,
        team_id=request.team_id,
        channel_id=request.channel_id,
        root_id=request.root_id,
        mode=binding.conversation_mode.value,
    )

    # 4. 대화 이력 로딩 (현재 질문 이전 turn만) — conversation_id로만 필터 (FR-CTX-002)
    history = deps.store.load_history(conversation_id, binding.history_turns * 2)

    # 3. user 메시지 저장
    deps.store.add_user_message(conversation_id, request.post_id, request.message)

    try:
        output = await deps.pipeline.run(question=request.message, binding=binding, history=history)
    except Exception as exc:  # noqa: BLE001 — 파이프라인 실패 시 오류 Post (FR-CHAT-009)
        deps.store.update_job_status(job_id, "FAILED", error=str(exc)[:500])
        await deps.delivery.deliver_error(
            binding=binding,
            request=request,
            text="⚠️ 답변 생성 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.",
        )
        raise

    latency_ms = int(output.usage.get("llm_ms", 0)) or None
    citation_dicts = [c.model_dump() for c in output.citations]
    message_id = deps.store.add_assistant_message(
        conversation_id, output.answer, latency_ms=latency_ms, citations=citation_dicts
    )

    completion = RagCompletion(
        message_id=message_id,
        answer=output.answer,
        citations=output.citations,
        insufficient_evidence=output.insufficient_evidence,
        usage=output.usage,
    )

    # 14. 게시 + delivery 기록
    result = await deps.delivery.deliver_answer(
        binding=binding, request=request, completion=completion, chat_job_id=job_id
    )
    deps.store.record_delivery(
        job_id,
        request.channel_id,
        attempt=result.attempts,
        status="SENT" if result.ok else "DEAD_LETTER",
        http_status=result.http_status,
    )

    # 15. Job 상태 확정
    deps.store.update_job_status(job_id, "COMPLETED" if result.ok else "DELIVERY_FAILED")
    _ = INSUFFICIENT_EVIDENCE_TEXT  # (답변 텍스트는 파이프라인에서 이미 처리)
    return completion


_deps: WorkerDeps | None = None


def get_worker_deps() -> WorkerDeps:
    """RQ Worker 프로세스 startup 시 실 어댑터로 1회 구성 (lazy singleton)."""
    global _deps
    if _deps is None:
        from rag.worker.bootstrap import build_worker_deps

        _deps = build_worker_deps()
    return _deps


def load_chat_request(job_id: str) -> ChatRequest:
    """bridge가 Redis `chat:req:{job_id}`에 보관한 ChatRequest를 로딩한다 (§7.1.1).

    이벤트 테이블에는 hash만 저장하므로(NFR-DATA-007) 질문 원문은 Redis에서 읽는다.
    """
    import redis

    from rag.core.config import get_settings

    conn = redis.Redis.from_url(get_settings().redis_url)
    raw = conn.get(f"chat:req:{job_id}")
    if raw is None:
        raise RuntimeError(f"chat request payload missing for job {job_id}")
    return ChatRequest.model_validate_json(raw)


def run_chat_job(job_id: str) -> None:
    """RQ entrypoint. bridge는 job_id만 enqueue하고 ChatRequest는 Redis에 보관한다 (§7.1.1)."""
    request = load_chat_request(job_id)
    asyncio.run(process_chat_job(get_worker_deps(), job_id, request))
