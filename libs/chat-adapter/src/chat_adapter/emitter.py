"""socket.io 이벤트 Emitter (§7.1.2). Worker 는 write-only Redis manager 로 room 에 직접 emit.

chat-gateway 의 AsyncServer 도 같은 Redis channel 을 구독하므로, 어느 gateway replica 에
붙은 브라우저든 이벤트를 받는다 (sticky session 불필요 — 클라이언트는 websocket 전용).
"""

from __future__ import annotations

import time
from typing import Any, Protocol

from rag_schemas.webchat import (
    WS_LLM_STREAM_DELTA,
    WS_LLM_STREAM_END,
    WS_POST_CREATED,
    WS_POST_DELETED,
    WS_POST_UPDATED,
    LlmStreamDelta,
    LlmStreamEnd,
    PostDeleted,
    PostDto,
    channel_room,
)

DEFAULT_FLUSH_MS = 50
DEFAULT_FLUSH_CHARS = 64


class SocketManager(Protocol):
    """socketio.AsyncRedisManager / AsyncServer 공통 emit 시그니처."""

    async def emit(
        self,
        event: str,
        data: Any,
        namespace: str | None = None,
        room: str | None = None,
        **kw: Any,
    ) -> Any: ...


class DeltaStream:
    """토큰 delta 를 묶어서(시간/길이 기준) emit — Redis/WS 메시지 폭주 방지."""

    def __init__(
        self,
        manager: SocketManager,
        *,
        post_id: str,
        channel_id: str,
        root_id: str | None,
        flush_ms: int = DEFAULT_FLUSH_MS,
        flush_chars: int = DEFAULT_FLUSH_CHARS,
        clock: Any = time.monotonic,
    ) -> None:
        self._m = manager
        self._post_id = post_id
        self._channel_id = channel_id
        self._root_id = root_id
        self._flush_s = flush_ms / 1000
        self._flush_chars = flush_chars
        self._clock = clock
        self._buf: list[str] = []
        self._buf_len = 0
        self._last = clock()
        self.seq = 0
        self.text = ""  # 누적 전체 텍스트 (최종 본문 검증용)

    async def push(self, delta: str) -> None:
        if not delta:
            return
        self._buf.append(delta)
        self._buf_len += len(delta)
        self.text += delta
        if self._buf_len >= self._flush_chars or self._clock() - self._last >= self._flush_s:
            await self.flush()

    async def flush(self) -> None:
        if not self._buf:
            return
        chunk = "".join(self._buf)
        self._buf, self._buf_len = [], 0
        self._last = self._clock()
        self.seq += 1
        payload = LlmStreamDelta(
            post_id=self._post_id,
            channel_id=self._channel_id,
            root_id=self._root_id,
            delta=chunk,
            seq=self.seq,
        )
        await self._m.emit(
            WS_LLM_STREAM_DELTA, payload.model_dump(), room=channel_room(self._channel_id)
        )


class StreamEmitter:
    def __init__(self, manager: SocketManager) -> None:
        self._m = manager

    def open_stream(self, *, post_id: str, channel_id: str, root_id: str | None) -> DeltaStream:
        return DeltaStream(self._m, post_id=post_id, channel_id=channel_id, root_id=root_id)

    async def post_created(self, post: PostDto) -> None:
        await self._m.emit(
            WS_POST_CREATED, post.model_dump(mode="json"), room=channel_room(post.channel_id)
        )

    async def post_updated(self, post: PostDto) -> None:
        await self._m.emit(
            WS_POST_UPDATED, post.model_dump(mode="json"), room=channel_room(post.channel_id)
        )

    async def post_deleted(self, payload: PostDeleted) -> None:
        await self._m.emit(
            WS_POST_DELETED, payload.model_dump(), room=channel_room(payload.channel_id)
        )

    async def end(
        self, *, post_id: str, channel_id: str, root_id: str | None, usage: dict | None = None
    ) -> None:
        payload = LlmStreamEnd(post_id=post_id, channel_id=channel_id, root_id=root_id, usage=usage)
        await self._m.emit(WS_LLM_STREAM_END, payload.model_dump(), room=channel_room(channel_id))


def redis_emitter(redis_url: str) -> StreamEmitter:
    """프로세스 외부(worker)에서 gateway 의 socket.io room 으로 emit 하는 Emitter."""
    import socketio

    return StreamEmitter(socketio.AsyncRedisManager(redis_url, write_only=True))
