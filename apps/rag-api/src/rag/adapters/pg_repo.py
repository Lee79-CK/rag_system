"""PostgreSQL 영속화 어댑터 — 대화/메시지/citation/job/delivery (§5, §7.2.1).

앱 간 코드 공유 금지(§2.1)이므로 admin-api ORM을 import하지 않고 SQLAlchemy Core SQL을 사용한다.
대화 이력 조회는 항상 conversation_id로 필터한다 (FR-CTX-002).
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from rag_schemas import (
    ChannelBinding,
    ChannelMode,
    ConversationMode,
    KnowledgeScope,
)
from sqlalchemy import Engine, text


class PgBindingReader:
    """(team_id, channel_id) → ChannelBinding. admin-api가 관리하는 테이블을 read-only 조회."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def get_binding(self, team_id: str, channel_id: str) -> ChannelBinding | None:
        sql = text(
            """
            SELECT b.id, c.team_id, c.channel_id, c.channel_name, b.mode, b.trigger_word,
                   b.enabled, b.history_turns, b.mention_user, b.ack_message_enabled,
                   b.feedback_enabled, b.secret_ref,
                   ks.filter_json, ks.conversation_mode
            FROM mattermost_channel_bindings b
            JOIN mattermost_channels c ON c.id = b.channel_ref
            LEFT JOIN knowledge_scopes ks ON ks.id = b.knowledge_scope_id
            WHERE c.team_id = :team_id AND c.channel_id = :channel_id
            """
        )
        with self._engine.connect() as conn:
            row = (
                conn.execute(sql, {"team_id": team_id, "channel_id": channel_id}).mappings().first()
            )
        if row is None:
            return None
        filter_json = row["filter_json"] or {}
        if isinstance(filter_json, str):
            filter_json = json.loads(filter_json)
        return ChannelBinding(
            id=str(row["id"]),
            team_id=row["team_id"],
            channel_id=row["channel_id"],
            channel_name=row["channel_name"],
            mode=ChannelMode(row["mode"]),
            trigger_word=row["trigger_word"],
            enabled=row["enabled"],
            conversation_mode=ConversationMode(row["conversation_mode"] or "CHANNEL"),
            history_turns=row["history_turns"],
            knowledge_scope=KnowledgeScope(**filter_json) if filter_json else KnowledgeScope(),
            incoming_webhook_secret_ref=row["secret_ref"],
            mention_user=row["mention_user"],
            ack_message_enabled=row["ack_message_enabled"],
            feedback_enabled=row["feedback_enabled"],
        )


class PgConversationStore:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def upsert_conversation(
        self, *, scope_key: str, team_id: str, channel_id: str, root_id: str | None, mode: str
    ) -> str:
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO channel_conversations (id, scope_key, team_id, channel_id, root_id, mode)
                    VALUES (gen_random_uuid(), :sk, :team, :chan, :root, :mode)
                    ON CONFLICT (scope_key) DO NOTHING
                    """
                ),
                {
                    "sk": scope_key,
                    "team": team_id,
                    "chan": channel_id,
                    "root": root_id,
                    "mode": mode,
                },
            )
            cid = conn.execute(
                text("SELECT id FROM channel_conversations WHERE scope_key = :sk"),
                {"sk": scope_key},
            ).scalar_one()
        return str(cid)

    def load_history(self, conversation_id: str, limit: int) -> list[tuple[str, str]]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT role, content FROM messages
                    WHERE conversation_id = :cid
                    ORDER BY created_at DESC LIMIT :n
                    """
                ),
                {"cid": conversation_id, "n": limit},
            ).all()
        return [(r.role, r.content) for r in reversed(rows)]

    def add_user_message(self, conversation_id: str, post_id: str, content: str) -> str:
        mid = str(uuid.uuid4())
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO messages (id, conversation_id, mattermost_post_id, role, content)
                    VALUES (:id, :cid, :post, 'user', :content)
                    """
                ),
                {"id": mid, "cid": conversation_id, "post": post_id, "content": content},
            )
        return mid

    def add_assistant_message(
        self,
        conversation_id: str,
        content: str,
        *,
        latency_ms: int | None,
        citations: list[dict[str, Any]],
    ) -> str:
        mid = str(uuid.uuid4())
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO messages (id, conversation_id, role, content, latency_ms)
                    VALUES (:id, :cid, 'assistant', :content, :lat)
                    """
                ),
                {"id": mid, "cid": conversation_id, "content": content, "lat": latency_ms},
            )
            for rank, c in enumerate(citations, 1):
                conn.execute(
                    text(
                        """
                        INSERT INTO citations (id, message_id, chunk_id, document_id, score, rank)
                        VALUES (gen_random_uuid(), :mid, :chunk, :doc, :score, :rank)
                        """
                    ),
                    {
                        "mid": mid,
                        "chunk": c["chunk_id"],
                        "doc": c.get("document_id"),
                        "score": c.get("score"),
                        "rank": rank,
                    },
                )
        return mid

    def claim_job(self, job_id: str) -> bool:
        """QUEUED 상태일 때만 RUNNING 으로 전이. rowcount==1 이면 이 워커가 선점한 것."""
        with self._engine.begin() as conn:
            result = conn.execute(
                text(
                    """
                    UPDATE chat_jobs SET status = 'RUNNING', started_at = now()
                    WHERE id = :id AND status = 'QUEUED'
                    """
                ),
                {"id": job_id},
            )
        return (result.rowcount or 0) == 1

    def update_job_status(
        self, job_id: str, status: str, *, error: str | None = None, mark_started: bool = False
    ) -> None:
        sets = ["status = :status"]
        if mark_started:
            sets.append("started_at = now()")
        if status in {"COMPLETED", "FAILED"}:
            sets.append("completed_at = now()")
        if error is not None:
            sets.append("error = :error")
        with self._engine.begin() as conn:
            conn.execute(
                text(f"UPDATE chat_jobs SET {', '.join(sets)} WHERE id = :id"),
                {"status": status, "error": error, "id": job_id},
            )

    def record_delivery(
        self, job_id: str, channel_id: str, *, attempt: int, status: str, http_status: int | None
    ) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO mattermost_deliveries
                        (id, chat_job_id, channel_id, attempt, status, http_status)
                    VALUES (gen_random_uuid(), :job, :chan, :attempt, :status, :http)
                    """
                ),
                {
                    "job": job_id,
                    "chan": channel_id,
                    "attempt": attempt,
                    "status": status,
                    "http": http_status,
                },
            )
