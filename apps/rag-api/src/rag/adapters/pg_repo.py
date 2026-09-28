"""PostgreSQL 영속화 어댑터 — 대화/메시지/citation/job/Bot Post 갱신 (§5, §7.2.1).

앱 간 코드 공유 금지(§2.1)이므로 admin-api ORM을 import하지 않고 SQLAlchemy Core SQL을 사용한다.
대화 이력 조회는 항상 conversation_id로 필터한다 (FR-CTX-002).
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from chat_adapter import PostRow
from rag_schemas import (
    ChannelBinding,
    ChannelMode,
    ConversationMode,
    KnowledgeScope,
)
from rag_schemas.webchat import UserBrief
from sqlalchemy import Engine, text


class PgBindingReader:
    """channel_id → ChannelBinding. admin-api가 관리하는 테이블을 read-only 조회."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def get_binding(self, channel_id: str) -> ChannelBinding | None:
        sql = text(
            """
            SELECT b.id, c.id AS channel_id, c.name AS channel_name, b.mode, b.trigger_word,
                   b.enabled, b.history_turns, b.mention_user, b.ack_message_enabled,
                   b.feedback_enabled, ks.filter_json, ks.conversation_mode
            FROM channel_bindings b
            JOIN chat_channels c ON c.id = b.channel_ref
            LEFT JOIN knowledge_scopes ks ON ks.id = b.knowledge_scope_id
            WHERE c.id = CAST(:channel_id AS uuid)
            ORDER BY b.enabled DESC, b.updated_at DESC
            LIMIT 1
            """
        )
        try:
            uuid.UUID(channel_id)
        except ValueError:
            return None
        with self._engine.connect() as conn:
            row = conn.execute(sql, {"channel_id": channel_id}).mappings().first()
        if row is None:
            return None
        filter_json = row["filter_json"] or {}
        if isinstance(filter_json, str):
            filter_json = json.loads(filter_json)
        return ChannelBinding(
            id=str(row["id"]),
            channel_id=str(row["channel_id"]),
            channel_name=row["channel_name"],
            mode=ChannelMode(row["mode"]),
            trigger_word=row["trigger_word"],
            enabled=row["enabled"],
            conversation_mode=ConversationMode(row["conversation_mode"] or "CHANNEL"),
            history_turns=row["history_turns"],
            knowledge_scope=KnowledgeScope(**filter_json) if filter_json else KnowledgeScope(),
            mention_user=row["mention_user"],
            ack_message_enabled=row["ack_message_enabled"],
            feedback_enabled=row["feedback_enabled"],
        )


class PgConversationStore:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def upsert_conversation(
        self, *, scope_key: str, channel_id: str, root_id: str | None, mode: str
    ) -> str:
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO channel_conversations (id, scope_key, channel_id, root_id, mode)
                    VALUES (gen_random_uuid(), :sk, :chan, :root, :mode)
                    ON CONFLICT (scope_key) DO NOTHING
                    """
                ),
                {
                    "sk": scope_key,
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
                    INSERT INTO messages (id, conversation_id, post_id, role, content)
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
        post_id: str,
        latency_ms: int | None,
        citations: list[dict[str, Any]],
    ) -> str:
        """assistant 답변 저장. post_id = Bot Post id (피드백 검증 시 Post→message 역조회)."""
        mid = str(uuid.uuid4())
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO messages (id, conversation_id, post_id, role, content, latency_ms)
                    VALUES (:id, :cid, :post, 'assistant', :content, :lat)
                    """
                ),
                {
                    "id": mid,
                    "cid": conversation_id,
                    "post": post_id,
                    "content": content,
                    "lat": latency_ms,
                },
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


class PgChatPostStore:
    """chat_posts 의 placeholder Bot Post 최종 갱신 (chat-gateway 가 생성한 행)."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def update_bot_post(
        self, post_id: str, *, message: str, blocks: list[dict[str, Any]], props: dict[str, Any]
    ) -> PostRow | None:
        with self._engine.begin() as conn:
            row = (
                conn.execute(
                    text(
                        """
                        UPDATE chat_posts p
                        SET message = :message,
                            blocks = CAST(:blocks AS jsonb),
                            props = p.props || CAST(:props AS jsonb)
                        FROM chat_users u
                        WHERE p.id = CAST(:id AS uuid) AND p.delete_at IS NULL
                          AND u.id = p.user_id
                        RETURNING p.id, p.channel_id, p.root_id, p.type, p.message, p.blocks,
                                  p.props, p.created_at, p.edit_at,
                                  u.id AS user_id, u.display_name, u.avatar_url, u.is_bot
                        """
                    ),
                    {
                        "id": post_id,
                        "message": message,
                        "blocks": json.dumps(blocks, ensure_ascii=False),
                        "props": json.dumps(props, ensure_ascii=False),
                    },
                )
                .mappings()
                .first()
            )
        if row is None:
            return None
        return PostRow(
            id=str(row["id"]),
            channel_id=str(row["channel_id"]),
            root_id=str(row["root_id"]) if row["root_id"] else None,
            type=row["type"],
            message=row["message"],
            blocks=row["blocks"],
            props=row["props"] or {},
            created_at=row["created_at"],
            edit_at=row["edit_at"],
            user=UserBrief(
                id=str(row["user_id"]),
                display_name=row["display_name"],
                avatar_url=row["avatar_url"],
                is_bot=row["is_bot"],
            ),
        )
