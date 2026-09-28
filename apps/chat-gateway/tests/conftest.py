"""공용 테스트 픽스처 — fakeredis + in-memory store + spy emitter + dependency_overrides."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import fakeredis.aioredis
import pytest
from chat_adapter import StreamEmitter, feedback_token
from fastapi.testclient import TestClient
from gateway.core.config import Settings
from gateway.core.security import issue_access_token
from gateway.deps import (
    provide_emitter,
    provide_enqueuer,
    provide_redis,
    provide_settings,
    provide_store,
)
from gateway.main import create_app
from gateway.repos import ChannelRecord, InMemoryChatStore, UserRecord
from rag_common.passwords import compute_prehash, hash_prehash
from rag_schemas import ChannelBinding, ChannelMode, KnowledgeScope

JWT_SECRET = "test-jwt-secret-0123456789abcdef"
PEPPER = "test-pepper-0123456789"
SIGNING_KEY = b"test-signing-key-0123456789"
PASSWORD = "Rag!Assistant2026"
SLUG = "rag"


class SpyEnqueuer:
    """RQ enqueue 스파이 — 호출 여부/횟수 검증용 (§7.1.3, §7.1.4 test_fb_no_rag_call)."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.fail = False

    def __call__(self, chat_job_id: str) -> str:
        if self.fail:
            raise ConnectionError("redis down")
        self.calls.append(chat_job_id)
        return chat_job_id


class SpyManager:
    def __init__(self) -> None:
        self.events: list[tuple[str, Any, str | None]] = []

    async def emit(self, event, data, namespace=None, room=None, **kw):
        self.events.append((event, data, room))

    def names(self) -> list[str]:
        return [e[0] for e in self.events]


@dataclass
class Harness:
    client: TestClient
    settings: Settings
    redis: Any
    store: InMemoryChatStore
    enqueuer: SpyEnqueuer
    sockets: SpyManager
    alice: UserRecord
    bob: UserRecord
    bot: UserRecord
    channel: ChannelRecord  # alice 멤버, DEDICATED
    other: ChannelRecord  # bob 만 멤버
    extra: dict = field(default_factory=dict)

    def token(self, user: UserRecord) -> str:
        return issue_access_token(self.settings, user_id=user.id, role=user.role)

    def auth(self, user: UserRecord | None = None) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token(user or self.alice)}"}

    def post(self, message: str, *, user: UserRecord | None = None, **over: Any):
        body = {"channel_id": self.channel.id, "message": message, "client_id": str(uuid.uuid4())}
        body.update(over)
        return self.client.post("/api/v1/posts", json=body, headers=self.auth(user))

    def login_body(self, email: str, password: str = PASSWORD, **over: Any) -> dict[str, Any]:
        body = {
            "email": email,
            "prehash": compute_prehash(SLUG, email, password, iterations=1000),
            "client_nonce": uuid.uuid4().hex,
            "timestamp": int(time.time() * 1000),
        }
        body.update(over)
        return body

    def answered_bot_post(self, *, channel: ChannelRecord | None = None) -> tuple[str, str, str]:
        """worker 가 답변을 완료한 상태를 재현 → (bot_post_id, message_id, feedback_token)."""
        from gateway.repos import AnswerRef

        ch = channel or self.channel
        q = self.store.create_question(
            channel_id=ch.id,
            root_id=None,
            user=self.alice,
            message="질문",
            client_id=None,
            bot=self.bot,
            bot_root_id=None,
            bot_props={"streaming": False},
        )
        assert q.bot_post is not None
        message_id = str(uuid.uuid4())
        self.store.answers[q.bot_post.id] = AnswerRef(message_id=message_id, channel_id=ch.id)
        return q.bot_post.id, message_id, feedback_token(SIGNING_KEY, message_id, q.bot_post.id)


def _secret(tmp_path, name: str, value: str) -> str:
    p = tmp_path / name
    p.write_text(value, encoding="utf-8")
    return str(p)


def make_settings(tmp_path) -> Settings:
    return Settings(
        jwt_secret_file=_secret(tmp_path, "jwt", JWT_SECRET),
        password_pepper_file=_secret(tmp_path, "pepper", PEPPER),
        feedback_signing_key_file=_secret(tmp_path, "fb", SIGNING_KEY.decode()),
        chat_workspace_slug=SLUG,
        cookie_secure=False,
        feedback_enabled=True,
        rate_limit_per_user_per_min=100,
        rate_limit_per_channel_per_min=100,
        rate_limit_feedback_per_user_per_min=20,
        rate_limit_login_per_min=100,
    )


def binding_for(channel: ChannelRecord, **over: Any) -> ChannelBinding:
    base: dict[str, Any] = {
        "id": f"b-{channel.id}",
        "channel_id": channel.id,
        "channel_name": channel.name,
        "mode": ChannelMode.DEDICATED_CHANNEL,
        "trigger_word": None,
        "enabled": True,
        "knowledge_scope": KnowledgeScope(),
    }
    base.update(over)
    return ChannelBinding(**base)


def _user(email: str, name: str, *, role: str = "user", is_bot: bool = False) -> UserRecord:
    pw = None
    if not is_bot:
        pw = hash_prehash(compute_prehash(SLUG, email, PASSWORD, iterations=1000), PEPPER.encode())
    return UserRecord(
        id=str(uuid.uuid4()),
        email=email,
        display_name=name,
        role=role,
        is_bot=is_bot,
        password_hash=pw,
    )


@pytest.fixture
def harness(tmp_path) -> Harness:
    settings = make_settings(tmp_path)
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    store = InMemoryChatStore()
    alice = _user("alice@example.com", "alice")
    bob = _user("bob@example.com", "bob")
    bot = _user("rag-bot@local", "RAG Assistant", is_bot=True)
    for u in (alice, bob, bot):
        store.users[u.id] = u
    channel = ChannelRecord(id=str(uuid.uuid4()), name="rag-cloud-ops", display_name="Cloud Ops")
    other = ChannelRecord(id=str(uuid.uuid4()), name="rag-hr", display_name="HR")
    store.channels = {channel.id: channel, other.id: other}
    store.members = {(channel.id, alice.id): "member", (other.id, bob.id): "member"}
    store.bindings = {channel.id: binding_for(channel), other.id: binding_for(other)}
    enqueuer = SpyEnqueuer()
    sockets = SpyManager()

    app = create_app()
    app.dependency_overrides[provide_settings] = lambda: settings
    app.dependency_overrides[provide_redis] = lambda: redis
    app.dependency_overrides[provide_store] = lambda: store
    app.dependency_overrides[provide_enqueuer] = lambda: enqueuer
    app.dependency_overrides[provide_emitter] = lambda: StreamEmitter(sockets)

    with TestClient(app) as client:
        yield Harness(
            client=client,
            settings=settings,
            redis=redis,
            store=store,
            enqueuer=enqueuer,
            sockets=sockets,
            alice=alice,
            bob=bob,
            bot=bot,
            channel=channel,
            other=other,
        )
