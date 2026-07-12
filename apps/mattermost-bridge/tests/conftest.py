"""공용 테스트 픽스처 — fakeredis + in-memory repos + dependency_overrides."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import fakeredis.aioredis
import pytest
from bridge.core.config import Settings
from bridge.deps import (
    provide_binding_cache,
    provide_binding_repo,
    provide_enqueuer,
    provide_event_repo,
    provide_feedback_repo,
    provide_redis,
    provide_settings,
)
from bridge.main import create_app
from bridge.repos import InMemoryBindingRepo, InMemoryEventRepo, InMemoryFeedbackRepo
from fastapi.testclient import TestClient
from mattermost_adapter import feedback_signature
from rag_common import TTLCache
from rag_schemas import ChannelBinding, ChannelMode, KnowledgeScope

TOKEN = "test-outgoing-token"
SIGNING_KEY = b"test-signing-key-0123456789"


class SpyEnqueuer:
    """RQ enqueue 스파이 — 호출 여부/횟수 검증용 (§7.1.3, §7.1.4 test_fb_no_rag_call)."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def __call__(self, chat_job_id: str) -> str:
        self.calls.append(chat_job_id)
        return chat_job_id


@dataclass
class Harness:
    client: TestClient
    settings: Settings
    redis: Any
    binding_repo: InMemoryBindingRepo
    event_repo: InMemoryEventRepo
    feedback_repo: InMemoryFeedbackRepo
    enqueuer: SpyEnqueuer
    signing_key: bytes = SIGNING_KEY
    extra: dict = field(default_factory=dict)

    def sign(self, message_id: str, value: str) -> str:
        return feedback_signature(self.signing_key, message_id, value)


def _make_settings(tmp_path) -> Settings:
    token_file = tmp_path / "outgoing-token"
    token_file.write_text(TOKEN, encoding="utf-8")
    key_file = tmp_path / "feedback-signing-key"
    key_file.write_bytes(SIGNING_KEY)
    return Settings(
        mattermost_outgoing_token_secret_file=str(token_file),
        feedback_signing_key_file=str(key_file),
        bridge_bot_username="RAG Assistant",
        bridge_allowed_source_cidrs="",  # 개방 (TestClient host는 IP가 아님)
        feedback_enabled=True,
        rate_limit_per_user_per_min=100,
        rate_limit_per_channel_per_min=100,
        rate_limit_feedback_per_user_per_min=20,
    )


def dedicated_binding(*, enabled: bool = True) -> ChannelBinding:
    return ChannelBinding(
        id="b1",
        team_id="team1",
        channel_id="chan1",
        channel_name="general",
        mode=ChannelMode.DEDICATED_CHANNEL,
        trigger_word=None,
        enabled=enabled,
        knowledge_scope=KnowledgeScope(),
        incoming_webhook_secret_ref="mm-chan1",
        ack_message_enabled=True,
    )


@pytest.fixture
def harness(tmp_path) -> Harness:
    settings = _make_settings(tmp_path)
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    binding_repo = InMemoryBindingRepo()
    binding_repo.add(dedicated_binding())
    event_repo = InMemoryEventRepo()
    feedback_repo = InMemoryFeedbackRepo()
    enqueuer = SpyEnqueuer()
    cache: TTLCache[str, ChannelBinding] = TTLCache(60)

    app = create_app()
    app.dependency_overrides[provide_settings] = lambda: settings
    app.dependency_overrides[provide_redis] = lambda: redis
    app.dependency_overrides[provide_binding_repo] = lambda: binding_repo
    app.dependency_overrides[provide_event_repo] = lambda: event_repo
    app.dependency_overrides[provide_feedback_repo] = lambda: feedback_repo
    app.dependency_overrides[provide_enqueuer] = lambda: enqueuer
    app.dependency_overrides[provide_binding_cache] = lambda: cache

    with TestClient(app) as client:
        yield Harness(
            client=client,
            settings=settings,
            redis=redis,
            binding_repo=binding_repo,
            event_repo=event_repo,
            feedback_repo=feedback_repo,
            enqueuer=enqueuer,
        )


def make_outgoing_payload(**over: Any) -> dict[str, Any]:
    payload = {
        "token": TOKEN,
        "team_id": "team1",
        "team_domain": "acme",
        "channel_id": "chan1",
        "channel_name": "general",
        "timestamp": 1234567890,
        "user_id": "user1",
        "user_name": "alice",
        "post_id": "post-1",
        "root_id": "",
        "text": "휴가 정책 알려줘",
        "trigger_word": "",
    }
    payload.update(over)
    return payload


def make_action_body(harness: Harness, **over: Any) -> dict[str, Any]:
    message_id = over.pop("message_id", "msg-1")
    value = over.pop("value", "UP")
    sig = over.pop("sig", None) or harness.sign(message_id, value)
    body = {
        "user_id": "user1",
        "user_name": "alice",
        "post_id": "answer-post-1",
        "channel_id": "chan1",
        "team_id": "team1",
        "context": {
            "action": "feedback",
            "message_id": message_id,
            "chat_job_id": "job-1",
            "value": value,
            "sig": sig,
        },
    }
    body.update(over)
    return body
