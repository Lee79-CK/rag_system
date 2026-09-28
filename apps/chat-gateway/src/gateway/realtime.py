"""socket.io 실시간 허브 (docs/TDD.md §7.1.2) — aiops_chatbot realtime.gateway 계약 호환.

- path `/ws`, websocket transport 전용 (polling 미허용 → 다중 replica 에서 sticky 불필요)
- handshake `auth.token` = access JWT. 실패 시 연결 거부.
- 연결 시 사용자가 **멤버인 채널 room 만** join (Channel 격리: 타 채널 이벤트 수신 불가)
- 다중 replica / rag-worker 간 브로드캐스트는 AsyncRedisManager(Redis pub/sub) 경유.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from rag_observability import get_logger
from rag_schemas.webchat import WS_READY, channel_room, user_room

from gateway.core.config import Settings
from gateway.core.security import Principal, verify_access_token
from gateway.metrics import gateway_ws_connections
from gateway.repos import ChatStore

log = get_logger(__name__)


class RealtimeHub:
    def __init__(
        self,
        sio: Any,
        *,
        settings: Callable[[], Settings],
        store: Callable[[], ChatStore],
    ) -> None:
        self.sio = sio
        self._settings = settings
        self._store = store
        sio.on("connect", self.on_connect)
        sio.on("disconnect", self.on_disconnect)
        sio.on("ack", self.on_ack)
        sio.on("subscribe", self.on_subscribe)
        sio.on("typing", self.on_typing)

    def authenticate(self, auth: Any) -> Principal | None:
        token = auth.get("token") if isinstance(auth, dict) else None
        if not isinstance(token, str):
            return None
        principal = verify_access_token(self._settings(), token)
        if principal is None:
            return None
        user = self._store().get_user(principal.user_id)
        if user is None or not user.is_active or user.is_bot:
            return None
        return principal

    async def _sync_rooms(self, sid: str, user_id: str) -> list[str]:
        """멤버십 기준으로 room 을 맞춘다 (탈퇴한 채널 room 은 leave)."""
        wanted = {channel_room(m.channel.id) for m in self._store().list_member_channels(user_id)}
        current = set(self.sio.rooms(sid)) - {sid, user_room(user_id)}
        for room in current - wanted:
            await self.sio.leave_room(sid, room)
        for room in wanted - current:
            await self.sio.enter_room(sid, room)
        await self.sio.enter_room(sid, user_room(user_id))
        return sorted(r.removeprefix("channel:") for r in wanted)

    async def on_connect(self, sid: str, environ: dict, auth: Any = None) -> None:
        import socketio

        principal = self.authenticate(auth)
        if principal is None:
            raise socketio.exceptions.ConnectionRefusedError("unauthorized")
        await self.sio.save_session(sid, {"user_id": principal.user_id})
        channels = await self._sync_rooms(sid, principal.user_id)
        gateway_ws_connections.inc()
        await self.sio.emit(
            WS_READY,
            {"channels": channels, "server_time": datetime.now(UTC).isoformat()},
            to=sid,
        )

    async def on_disconnect(self, sid: str, *args: Any) -> None:
        gateway_ws_connections.dec()

    async def _user_id(self, sid: str) -> str | None:
        try:
            session = await self.sio.get_session(sid)
        except KeyError:
            return None
        return session.get("user_id")

    async def on_ack(self, sid: str, data: Any = None) -> dict[str, list]:
        """재연결 직후 누락분 조회. chat-web 은 재연결 시 전체 재조회하므로 빈 목록 + room 재동기화."""
        uid = await self._user_id(sid)
        if uid:
            await self._sync_rooms(sid, uid)
        return {"missed": []}

    async def on_subscribe(self, sid: str, data: Any = None) -> dict[str, Any]:
        uid = await self._user_id(sid)
        channels = await self._sync_rooms(sid, uid) if uid else []
        return {"channels": channels}

    async def on_typing(self, sid: str, data: Any = None) -> None:
        return None  # 타이핑 인디케이터 미사용 (Web Chat 범위 외)


def origin_checker(extra_origins: list[str]) -> Callable[[str | None, dict], bool]:
    """WebSocket Origin 검사 (CSWSH 방지).

    engineio 는 허용 목록을 주면 same-origin 을 자동 허용하지 않는다 → K8s Ingress(동일 출처)
    에서 전부 거부되는 문제를 피하려고 same-origin(Host / X-Forwarded-Host) + 명시 목록을 허용한다.
    """
    allowed_extra = set(extra_origins)

    def _check(origin: str | None, environ: dict) -> bool:
        if not origin:
            return True  # 브라우저 외 클라이언트 (Origin 없음) — 인증은 handshake 토큰으로 강제
        if origin in allowed_extra:
            return True
        hosts = {environ.get("HTTP_HOST", "")}
        fwd = environ.get("HTTP_X_FORWARDED_HOST")
        if fwd:
            hosts.add(fwd.split(",")[0].strip())
        return origin.split("://", 1)[-1] in {h for h in hosts if h}

    return _check


def build_socket_server(settings: Settings) -> Any:
    import socketio

    return socketio.AsyncServer(
        async_mode="asgi",
        client_manager=socketio.AsyncRedisManager(settings.redis_url),
        cors_allowed_origins=origin_checker(settings.cors_origins()),
        transports=["websocket"],
        logger=False,
        engineio_logger=False,
    )
