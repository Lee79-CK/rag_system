"""데이터 접근 계층 (docs/TDD.md §5, §5.1).

Bridge가 접근하는 테이블 (§5.1 경계):
- 쓰기: `mattermost_events`, `chat_jobs`, `mattermost_deliveries`
- (피드백 경로) 읽기: `messages` (+ `channel_conversations` 조인), 쓰기: `message_feedback`
- (수신 경로) 읽기: binding 조회용 `mattermost_channel_bindings`/`mattermost_channels`/`knowledge_scopes`

Protocol + SQLAlchemy(동기, 단기 세션) 구현 + 테스트용 in-memory Fake 를 제공한다.
문서/설정 테이블에는 접근하지 않는다.
"""

from __future__ import annotations

import uuid
from typing import Any, Protocol

from rag_schemas import (
    ChannelBinding,
    ChannelMode,
    ConversationMode,
    FeedbackValue,
    KnowledgeScope,
)

# --------------------------------------------------------------------------- #
# Protocols
# --------------------------------------------------------------------------- #


class BindingRepo(Protocol):
    def get_binding(self, team_id: str, channel_id: str) -> ChannelBinding | None: ...


class EventRepo(Protocol):
    def record_event(
        self,
        *,
        post_id: str,
        root_id: str | None,
        team_id: str,
        channel_id: str,
        user_id: str,
        payload_hash: str,
        status: str = "ACCEPTED",
    ) -> str: ...

    def create_chat_job(self, event_id: str, conversation_id: str | None = None) -> str: ...

    def record_event_and_job(
        self,
        *,
        post_id: str,
        root_id: str | None,
        team_id: str,
        channel_id: str,
        user_id: str,
        payload_hash: str,
        conversation_id: str | None = None,
    ) -> tuple[str, str]:
        """이벤트 INSERT + Job INSERT 를 단일 트랜잭션으로 수행 (§7.1.1 step8 MUST)."""
        ...

    def discard_event_and_job(self, event_id: str, job_id: str) -> None:
        """enqueue 실패 시 보상 트랜잭션 — step8 에서 만든 두 행을 삭제해 재수신을 허용한다."""
        ...


class FeedbackRepo(Protocol):
    def message_exists(self, message_id: str) -> bool: ...

    def message_exists_in_channel(self, message_id: str, channel_id: str) -> bool: ...

    def upsert_feedback(
        self, message_id: str, user_id: str, value: FeedbackValue, channel_id: str
    ) -> None: ...


# --------------------------------------------------------------------------- #
# SQLAlchemy (sync, 단기 세션) 구현
# --------------------------------------------------------------------------- #


def _make_engine(dsn: str) -> Any:
    from sqlalchemy import create_engine

    return create_engine(dsn, pool_pre_ping=True, future=True)


class SqlBindingRepo:
    """binding 조회 — Redis 캐시 미스 시 PG fallback (§7.1.1 step4)."""

    def __init__(self, engine: Any) -> None:
        self._engine = engine

    def get_binding(self, team_id: str, channel_id: str) -> ChannelBinding | None:
        from sqlalchemy import text

        sql = text(
            """
            SELECT b.id, c.team_id, c.channel_id, c.channel_name, b.mode,
                   b.trigger_word, b.enabled, b.history_turns, b.mention_user,
                   b.ack_message_enabled, b.secret_ref,
                   ks.filter_json, ks.conversation_mode
            FROM mattermost_channel_bindings b
            JOIN mattermost_channels c ON c.id = b.channel_ref
            LEFT JOIN knowledge_scopes ks ON ks.id = b.knowledge_scope_id
            WHERE c.team_id = :team_id AND c.channel_id = :channel_id
            LIMIT 1
            """
        )
        with self._engine.connect() as conn:
            row = (
                conn.execute(sql, {"team_id": team_id, "channel_id": channel_id}).mappings().first()
            )
        if row is None:
            return None

        scope_filter = row["filter_json"] or {}
        conv_mode = row["conversation_mode"] or ConversationMode.CHANNEL.value
        return ChannelBinding(
            id=str(row["id"]),
            team_id=row["team_id"],
            channel_id=row["channel_id"],
            channel_name=row["channel_name"],
            mode=ChannelMode(row["mode"]),
            trigger_word=row["trigger_word"],
            enabled=row["enabled"],
            conversation_mode=ConversationMode(conv_mode),
            history_turns=row["history_turns"],
            knowledge_scope=KnowledgeScope.model_validate(scope_filter),
            incoming_webhook_secret_ref=row["secret_ref"],
            mention_user=row["mention_user"],
            ack_message_enabled=row["ack_message_enabled"],
        )


class SqlEventRepo:
    def __init__(self, engine: Any) -> None:
        self._engine = engine

    def record_event(
        self,
        *,
        post_id: str,
        root_id: str | None,
        team_id: str,
        channel_id: str,
        user_id: str,
        payload_hash: str,
        status: str = "ACCEPTED",
    ) -> str:
        from sqlalchemy import text

        sql = text(
            """
            INSERT INTO mattermost_events
                (post_id, root_id, team_id, channel_id, user_id, payload_hash, status)
            VALUES (:post_id, :root_id, :team_id, :channel_id, :user_id, :payload_hash, :status)
            RETURNING id
            """
        )
        with self._engine.begin() as conn:
            event_id = conn.execute(
                sql,
                {
                    "post_id": post_id,
                    "root_id": root_id,
                    "team_id": team_id,
                    "channel_id": channel_id,
                    "user_id": user_id,
                    "payload_hash": payload_hash,
                    "status": status,
                },
            ).scalar_one()
        return str(event_id)

    def create_chat_job(self, event_id: str, conversation_id: str | None = None) -> str:
        from sqlalchemy import text

        sql = text(
            """
            INSERT INTO chat_jobs (event_id, conversation_id, status)
            VALUES (:event_id, :conversation_id, 'QUEUED')
            RETURNING id
            """
        )
        with self._engine.begin() as conn:
            job_id = conn.execute(
                sql, {"event_id": event_id, "conversation_id": conversation_id}
            ).scalar_one()
        return str(job_id)

    def record_event_and_job(
        self,
        *,
        post_id: str,
        root_id: str | None,
        team_id: str,
        channel_id: str,
        user_id: str,
        payload_hash: str,
        conversation_id: str | None = None,
    ) -> tuple[str, str]:
        from sqlalchemy import text

        insert_event = text(
            """
            INSERT INTO mattermost_events
                (post_id, root_id, team_id, channel_id, user_id, payload_hash, status)
            VALUES (:post_id, :root_id, :team_id, :channel_id, :user_id, :payload_hash, 'ACCEPTED')
            RETURNING id
            """
        )
        insert_job = text(
            """
            INSERT INTO chat_jobs (event_id, conversation_id, status)
            VALUES (:event_id, :conversation_id, 'QUEUED')
            RETURNING id
            """
        )
        with self._engine.begin() as conn:  # 단일 트랜잭션 (§7.1.1 step8 MUST)
            event_id = conn.execute(
                insert_event,
                {
                    "post_id": post_id,
                    "root_id": root_id,
                    "team_id": team_id,
                    "channel_id": channel_id,
                    "user_id": user_id,
                    "payload_hash": payload_hash,
                },
            ).scalar_one()
            job_id = conn.execute(
                insert_job, {"event_id": event_id, "conversation_id": conversation_id}
            ).scalar_one()
        return str(event_id), str(job_id)

    def discard_event_and_job(self, event_id: str, job_id: str) -> None:
        from sqlalchemy import text

        with self._engine.begin() as conn:  # 보상 트랜잭션 (enqueue 실패)
            conn.execute(text("DELETE FROM chat_jobs WHERE id = :jid"), {"jid": job_id})
            conn.execute(text("DELETE FROM mattermost_events WHERE id = :eid"), {"eid": event_id})


class SqlFeedbackRepo:
    def __init__(self, engine: Any) -> None:
        self._engine = engine

    def message_exists(self, message_id: str) -> bool:
        from sqlalchemy import text

        sql = text("SELECT 1 FROM messages WHERE id = :mid LIMIT 1")
        with self._engine.connect() as conn:
            return conn.execute(sql, {"mid": message_id}).first() is not None

    def message_exists_in_channel(self, message_id: str, channel_id: str) -> bool:
        from sqlalchemy import text

        sql = text(
            """
            SELECT 1
            FROM messages m
            JOIN channel_conversations c ON c.id = m.conversation_id
            WHERE m.id = :mid AND c.channel_id = :cid
            LIMIT 1
            """
        )
        with self._engine.connect() as conn:
            return conn.execute(sql, {"mid": message_id, "cid": channel_id}).first() is not None

    def upsert_feedback(
        self, message_id: str, user_id: str, value: FeedbackValue, channel_id: str
    ) -> None:
        from sqlalchemy import text

        sql = text(
            """
            INSERT INTO message_feedback (message_id, mattermost_user_id, value, channel_id)
            VALUES (:mid, :uid, :value, :cid)
            ON CONFLICT (message_id, mattermost_user_id)
            DO UPDATE SET value = EXCLUDED.value,
                          channel_id = EXCLUDED.channel_id,
                          updated_at = now()
            """
        )
        with self._engine.begin() as conn:
            conn.execute(
                sql,
                {"mid": message_id, "uid": user_id, "value": value.value, "cid": channel_id},
            )


# --------------------------------------------------------------------------- #
# In-memory Fakes (테스트용)
# --------------------------------------------------------------------------- #


class InMemoryBindingRepo:
    def __init__(self) -> None:
        self._bindings: dict[tuple[str, str], ChannelBinding] = {}

    def add(self, binding: ChannelBinding) -> None:
        self._bindings[(binding.team_id, binding.channel_id)] = binding

    def get_binding(self, team_id: str, channel_id: str) -> ChannelBinding | None:
        return self._bindings.get((team_id, channel_id))


class InMemoryEventRepo:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.jobs: list[dict[str, Any]] = []
        self._seen_post_ids: set[str] = set()

    def record_event(
        self,
        *,
        post_id: str,
        root_id: str | None,
        team_id: str,
        channel_id: str,
        user_id: str,
        payload_hash: str,
        status: str = "ACCEPTED",
    ) -> str:
        if post_id in self._seen_post_ids:
            raise ValueError(f"duplicate post_id: {post_id}")  # post_id UNIQUE (2차 방어선)
        self._seen_post_ids.add(post_id)
        event_id = str(uuid.uuid4())
        self.events.append(
            {
                "id": event_id,
                "post_id": post_id,
                "root_id": root_id,
                "team_id": team_id,
                "channel_id": channel_id,
                "user_id": user_id,
                "payload_hash": payload_hash,
                "status": status,
            }
        )
        return event_id

    def create_chat_job(self, event_id: str, conversation_id: str | None = None) -> str:
        job_id = str(uuid.uuid4())
        self.jobs.append(
            {
                "id": job_id,
                "event_id": event_id,
                "conversation_id": conversation_id,
                "status": "QUEUED",
            }
        )
        return job_id

    def record_event_and_job(
        self,
        *,
        post_id: str,
        root_id: str | None,
        team_id: str,
        channel_id: str,
        user_id: str,
        payload_hash: str,
        conversation_id: str | None = None,
    ) -> tuple[str, str]:
        event_id = self.record_event(
            post_id=post_id,
            root_id=root_id,
            team_id=team_id,
            channel_id=channel_id,
            user_id=user_id,
            payload_hash=payload_hash,
        )
        job_id = self.create_chat_job(event_id, conversation_id)
        return event_id, job_id

    def discard_event_and_job(self, event_id: str, job_id: str) -> None:
        self.jobs = [j for j in self.jobs if j["id"] != job_id]
        removed = [e for e in self.events if e["id"] == event_id]
        self.events = [e for e in self.events if e["id"] != event_id]
        for e in removed:
            self._seen_post_ids.discard(e["post_id"])  # post_id UNIQUE 해제 → 재수신 가능


class InMemoryFeedbackRepo:
    def __init__(self) -> None:
        # message_id -> channel_id (답변 Post 소속)
        self._messages: dict[str, str] = {}
        # (message_id, user_id) -> feedback row
        self.feedback: dict[tuple[str, str], dict[str, Any]] = {}

    def add_message(self, message_id: str, channel_id: str) -> None:
        self._messages[message_id] = channel_id

    def message_exists(self, message_id: str) -> bool:
        return message_id in self._messages

    def message_exists_in_channel(self, message_id: str, channel_id: str) -> bool:
        return self._messages.get(message_id) == channel_id

    def upsert_feedback(
        self, message_id: str, user_id: str, value: FeedbackValue, channel_id: str
    ) -> None:
        key = (message_id, user_id)
        existing = self.feedback.get(key)
        if existing is None:
            self.feedback[key] = {
                "message_id": message_id,
                "user_id": user_id,
                "value": value,
                "channel_id": channel_id,
            }
        else:
            existing["value"] = value  # 재클릭 = 의견 변경 (행 수 유지)
