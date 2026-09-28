"""socket.io 허브 테스트 (docs/TDD.md §7.1.2) — handshake 인증 + 채널 room 격리."""

from __future__ import annotations

import pytest
from gateway.realtime import RealtimeHub, origin_checker


class FakeSio:
    def __init__(self) -> None:
        self.handlers: dict[str, object] = {}
        self._rooms: dict[str, set[str]] = {}
        self.sessions: dict[str, dict] = {}
        self.emitted: list[tuple[str, dict, str | None]] = []

    def on(self, event, handler):
        self.handlers[event] = handler

    def rooms(self, sid):
        return list(self._rooms.get(sid, {sid}))

    async def enter_room(self, sid, room):
        self._rooms.setdefault(sid, {sid}).add(room)

    async def leave_room(self, sid, room):
        self._rooms.get(sid, set()).discard(room)

    async def save_session(self, sid, data):
        self.sessions[sid] = data

    async def get_session(self, sid):
        return self.sessions[sid]

    async def emit(self, event, data, to=None, room=None):
        self.emitted.append((event, data, to or room))


@pytest.fixture
def hub(harness):
    sio = FakeSio()
    return RealtimeHub(sio, settings=lambda: harness.settings, store=lambda: harness.store), sio


async def test_ws_connect_rejects_bad_token(hub):
    import socketio

    h, _ = hub
    with pytest.raises(socketio.exceptions.ConnectionRefusedError):
        await h.on_connect("sid1", {}, {"token": "forged"})
    with pytest.raises(socketio.exceptions.ConnectionRefusedError):
        await h.on_connect("sid1", {}, None)


async def test_ws_joins_only_member_channel_rooms(hub, harness):
    h, sio = hub
    await h.on_connect("sid1", {}, {"token": harness.token(harness.alice)})
    rooms = set(sio.rooms("sid1"))
    assert f"channel:{harness.channel.id}" in rooms
    assert f"channel:{harness.other.id}" not in rooms  # 비멤버 채널 이벤트 수신 불가
    ready = sio.emitted[0]
    assert ready[0] == "ready" and ready[1]["channels"] == [harness.channel.id]


async def test_ws_ack_resyncs_rooms_after_membership_removed(hub, harness):
    h, sio = hub
    await h.on_connect("sid1", {}, {"token": harness.token(harness.alice)})
    del harness.store.members[(harness.channel.id, harness.alice.id)]
    assert await h.on_ack("sid1", {"since": "x"}) == {"missed": []}
    assert f"channel:{harness.channel.id}" not in set(sio.rooms("sid1"))


async def test_ws_bot_token_rejected(hub, harness):
    import socketio

    h, _ = hub
    with pytest.raises(socketio.exceptions.ConnectionRefusedError):
        await h.on_connect("sid1", {}, {"token": harness.token(harness.bot)})


def test_ws_origin_same_origin_and_allowlist():
    check = origin_checker(["http://localhost:3000"])
    ingress = {"HTTP_HOST": "chat.rag.local"}
    assert check("https://chat.rag.local", ingress)  # K8s Ingress 동일 출처
    assert check("http://localhost:3000", {"HTTP_HOST": "localhost:8001"})  # dev 교차 출처
    assert check(
        "https://chat.rag.local",
        {"HTTP_HOST": "gw:8001", "HTTP_X_FORWARDED_HOST": "chat.rag.local"},
    )
    assert not check("https://evil.example", ingress)  # CSWSH 차단
