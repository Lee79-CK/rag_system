"""Web Chat 답변 전달 어댑터 (DeliveryPort 구현) — §7.1.2, §7.2.5.

1. 스트리밍: 토큰 delta → socket.io `llm.stream.delta` (room=channel:{id}), best-effort.
2. 완료: chat_posts 의 placeholder Bot Post 를 최종 본문/blocks/props 로 갱신(SSOT) 후
   `post.updated` + `llm.stream.end` emit. 클라이언트는 end 수신 시 재조회하므로
   delta 유실이 있어도 최종 결과는 DB 기준으로 일치한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from chat_adapter import (
    ERROR_TEXT,
    DeltaStream,
    PostRow,
    StreamEmitter,
    feedback_token,
    render_answer,
    to_post_dto,
)
from rag_observability import get_logger
from rag_schemas import ChannelBinding, ChatRequest, RagCompletion

log = get_logger(__name__)


class BotPostStore(Protocol):
    def update_bot_post(
        self, post_id: str, *, message: str, blocks: list[dict[str, Any]], props: dict[str, Any]
    ) -> PostRow | None: ...


class SafeStream:
    """emit 실패가 답변 생성을 중단시키지 않도록 감싼 DeltaStream."""

    def __init__(self, inner: DeltaStream) -> None:
        self._inner = inner
        self._broken = False

    async def push(self, delta: str) -> None:
        if self._broken:
            return
        try:
            await self._inner.push(delta)
        except Exception as exc:  # noqa: BLE001 — 스트리밍은 best-effort
            self._broken = True
            log.warning("stream_emit_failed", error=type(exc).__name__)

    async def flush(self) -> None:
        if self._broken:
            return
        try:
            await self._inner.flush()
        except Exception as exc:  # noqa: BLE001
            self._broken = True
            log.warning("stream_emit_failed", error=type(exc).__name__)


@dataclass(slots=True)
class DeliveryDeps:
    posts: BotPostStore
    emitter: StreamEmitter
    signing_key: bytes  # FEEDBACK_SIGNING_KEY 파일 내용 (repr/log 금지)


class WebChatDelivery:
    def __init__(self, deps: DeliveryDeps) -> None:
        self._d = deps

    def open_stream(self, request: ChatRequest) -> SafeStream:
        return SafeStream(
            self._d.emitter.open_stream(
                post_id=request.bot_post_id,
                channel_id=request.channel_id,
                root_id=request.root_id,
            )
        )

    async def deliver_answer(
        self,
        *,
        binding: ChannelBinding,
        request: ChatRequest,
        completion: RagCompletion,
        chat_job_id: str,
    ) -> bool:
        message, blocks = render_answer(
            completion, user_name=request.user_name, mention=binding.mention_user
        )
        props: dict[str, Any] = {
            "streaming": False,
            "kind": "answer",  # props 는 jsonb merge — 이전 상태(error 등)를 명시적으로 덮어쓴다
            "chat_job_id": chat_job_id,
            "citations_count": len(completion.citations),
            "insufficient_evidence": completion.insufficient_evidence,
        }
        if binding.feedback_enabled and completion.message_id:
            props["feedback_token"] = feedback_token(
                self._d.signing_key, completion.message_id, request.bot_post_id
            )
        return await self._finalize(
            request, message=message, blocks=blocks, props=props, usage=completion.usage
        )

    async def deliver_error(self, *, request: ChatRequest, text: str = ERROR_TEXT) -> bool:
        props = {"streaming": False, "kind": "error"}
        return await self._finalize(request, message=text, blocks=[], props=props, usage=None)

    async def _finalize(
        self,
        request: ChatRequest,
        *,
        message: str,
        blocks: list[dict[str, Any]],
        props: dict[str, Any],
        usage: dict[str, Any] | None,
    ) -> bool:
        try:
            row = self._d.posts.update_bot_post(
                request.bot_post_id, message=message, blocks=blocks, props=props
            )
        except Exception as exc:  # noqa: BLE001
            log.error("bot_post_update_failed", error=type(exc).__name__)
            return False
        if row is None:  # 사용자가 질문/답변 Post 를 삭제한 경우
            log.warning("bot_post_missing", post_id=request.bot_post_id)
            return False
        try:
            await self._d.emitter.post_updated(to_post_dto(row))
            await self._d.emitter.end(
                post_id=request.bot_post_id,
                channel_id=request.channel_id,
                root_id=request.root_id,
                usage={k: v for k, v in (usage or {}).items() if k.endswith("_tokens")} or None,
            )
        except Exception as exc:  # noqa: BLE001 — DB 는 갱신됨. 클라이언트는 재조회로 수렴
            log.warning("final_emit_failed", error=type(exc).__name__)
            return False
        return True
