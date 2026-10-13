"""데이터 접근 계층 (docs/TDD.md §5, §5.1).

Gateway 가 접근하는 테이블 (§5.1 경계):
- 쓰기: `chat_posts`, `chat_jobs`, `chat_refresh_tokens`, `chat_channel_members.last_viewed_at`,
        `chat_users.password_hash`, `message_feedback`
- 읽기: `chat_users`, `chat_channels`, `chat_channel_members`, `channel_bindings`,
        `knowledge_scopes`, `messages`(+`channel_conversations`) — 피드백 대상 검증
문서/설정 테이블에는 접근하지 않는다.

Protocol + SQLAlchemy(동기, 단기 세션) 구현 + 테스트용 in-memory Fake 를 제공한다.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from chat_adapter import PostRow
from rag_schemas import (
    ChannelBinding,
    ChannelMode,
    ConversationMode,
    FeedbackValue,
    KnowledgeScope,
)
from rag_schemas.webchat import UserBrief

BOT_ROOT_SELF = "__self__"  # create_question(bot_root_id=...) — 질문 Post 자신을 thread root 로

# --------------------------------------------------------------------------- #
# Records
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class UserRecord:
    id: str
    email: str
    display_name: str
    role: str  # user|admin
    is_bot: bool = False
    is_active: bool = True
    password_hash: str | None = None  # repr/log 금지 대상 — 응답 DTO 로 변환 시 제외
    must_change_password: bool = False
    avatar_url: str | None = None

    def brief(self) -> UserBrief:
        return UserBrief(
            id=self.id,
            display_name=self.display_name,
            avatar_url=self.avatar_url,
            is_bot=self.is_bot,
        )

    def __repr__(self) -> str:  # password_hash 노출 방지
        return f"UserRecord(id={self.id!r}, role={self.role!r}, is_bot={self.is_bot})"


@dataclass(slots=True)
class ChannelRecord:
    id: str
    name: str
    display_name: str
    type: str = "public"  # public|private
    purpose: str | None = None


@dataclass(slots=True)
class MemberChannel:
    channel: ChannelRecord
    role: str
    unread: int = 0


@dataclass(slots=True)
class QuestionResult:
    user_post: PostRow
    bot_post: PostRow | None = None
    job_id: str | None = None


@dataclass(slots=True)
class AnswerRef:
    """Bot Post → 답변 message 역참조 (피드백 검증용)."""

    message_id: str
    channel_id: str


# --------------------------------------------------------------------------- #
# Protocol
# --------------------------------------------------------------------------- #


class ChatStore(Protocol):
    # users / auth
    def get_user_by_email(self, email: str) -> UserRecord | None: ...
    def get_user(self, user_id: str) -> UserRecord | None: ...
    def get_bot_user(self) -> UserRecord | None: ...
    def set_password(self, user_id: str, password_hash: str) -> None: ...
    def create_refresh(self, user_id: str, token_hash: str, expires_at: datetime) -> None: ...
    def consume_refresh(self, token_hash: str) -> str | None: ...
    def revoke_refresh(self, token_hash: str) -> None: ...

    # channels
    def list_member_channels(self, user_id: str) -> list[MemberChannel]: ...
    def get_channel(self, id_or_name: str) -> ChannelRecord | None: ...
    def get_member_role(self, channel_id: str, user_id: str) -> str | None: ...
    def list_members(self, channel_id: str) -> list[UserRecord]: ...
    def mark_viewed(self, channel_id: str, user_id: str) -> None: ...
    def get_binding(self, channel_id: str) -> ChannelBinding | None: ...

    # posts
    def get_post(self, post_id: str) -> PostRow | None: ...
    def list_root_posts(
        self, channel_id: str, *, limit: int, before: str | None
    ) -> tuple[list[PostRow], bool]: ...
    def list_replies(self, root_id: str) -> list[PostRow]: ...
    def thread_has_bot(self, root_id: str) -> bool: ...
    def create_post(
        self,
        *,
        channel_id: str,
        root_id: str | None,
        user: UserRecord,
        message: str,
        client_id: str | None,
    ) -> PostRow: ...
    def create_question(
        self,
        *,
        channel_id: str,
        root_id: str | None,
        user: UserRecord,
        message: str,
        client_id: str | None,
        bot: UserRecord,
        bot_root_id: str | None,
        bot_props: dict[str, Any],
    ) -> QuestionResult: ...
    def update_post(
        self, post_id: str, *, message: str | None = None, props: dict[str, Any] | None = None
    ) -> PostRow | None: ...
    def soft_delete_post(self, post_id: str) -> PostRow | None: ...
    def mark_job_failed(self, job_id: str, error: str) -> None: ...

    # feedback
    def get_answer_ref(self, bot_post_id: str) -> AnswerRef | None: ...
    def upsert_feedback(
        self, message_id: str, user_id: str, value: FeedbackValue, channel_id: str
    ) -> None: ...
    def feedback_counts(self, message_id: str) -> dict[str, int]: ...


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def _now() -> datetime:
    return datetime.now(UTC)


def _is_uuid(v: str) -> bool:
    try:
        uuid.UUID(v)
    except (ValueError, TypeError):
        return False
    return True


def _binding_from_row(row: Any) -> ChannelBinding:
    scope_filter = row["filter_json"] or {}
    if isinstance(scope_filter, str):
        scope_filter = json.loads(scope_filter)
    return ChannelBinding(
        id=str(row["id"]),
        channel_id=str(row["channel_id"]),
        channel_name=row["channel_name"],
        mode=ChannelMode(row["mode"]),
        trigger_word=row["trigger_word"],
        enabled=row["enabled"],
        conversation_mode=ConversationMode(row["conversation_mode"] or "CHANNEL"),
        history_turns=row["history_turns"],
        knowledge_scope=KnowledgeScope.model_validate(scope_filter),
        mention_user=row["mention_user"],
        ack_message_enabled=row["ack_message_enabled"],
        feedback_enabled=row["feedback_enabled"],
        direct_llm_enabled=row["direct_llm_enabled"],
    )


def _user_from_row(row: Any, prefix: str = "") -> UserRecord:
    return UserRecord(
        id=str(row[f"{prefix}id"]),
        email=row[f"{prefix}email"],
        display_name=row[f"{prefix}display_name"],
        role=row[f"{prefix}role"],
        is_bot=row[f"{prefix}is_bot"],
        is_active=row[f"{prefix}is_active"],
        password_hash=row.get(f"{prefix}password_hash"),
        must_change_password=row[f"{prefix}must_change_password"],
        avatar_url=row[f"{prefix}avatar_url"],
    )


# --------------------------------------------------------------------------- #
# SQLAlchemy (sync, 단기 세션) 구현
# --------------------------------------------------------------------------- #


def _make_engine(dsn: str) -> Any:
    from sqlalchemy import create_engine

    return create_engine(dsn, pool_pre_ping=True, future=True)


_USER_COLS = (
    "u.id, u.email, u.display_name, u.role, u.is_bot, u.is_active, u.password_hash,"
    " u.must_change_password, u.avatar_url"
)

_POST_SELECT = """
    SELECT p.id, p.channel_id, p.root_id, p.type, p.message, p.blocks, p.props,
           p.created_at, p.edit_at, p.delete_at,
           u.id AS u_id, u.display_name AS u_display_name, u.avatar_url AS u_avatar_url,
           u.is_bot AS u_is_bot,
           (SELECT count(*) FROM chat_posts r
             WHERE r.root_id = p.id AND r.delete_at IS NULL) AS reply_count,
           (SELECT max(r.created_at) FROM chat_posts r
             WHERE r.root_id = p.id AND r.delete_at IS NULL) AS last_reply_at
    FROM chat_posts p
    LEFT JOIN chat_users u ON u.id = p.user_id
"""


def _post_from_row(row: Any, participants: list[UserBrief] | None = None) -> PostRow:
    user = None
    if row["u_id"] is not None:
        user = UserBrief(
            id=str(row["u_id"]),
            display_name=row["u_display_name"],
            avatar_url=row["u_avatar_url"],
            is_bot=row["u_is_bot"],
        )
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
        delete_at=row["delete_at"],
        user=user,
        reply_count=int(row["reply_count"] or 0),
        last_reply_at=row["last_reply_at"],
        participants=participants or [],
    )


class SqlChatStore:
    def __init__(self, engine: Any) -> None:
        self._engine = engine

    # ------------------------------------------------------------ users / auth
    def _one_user(self, where: str, params: dict[str, Any]) -> UserRecord | None:
        from sqlalchemy import text

        sql = text(f"SELECT {_USER_COLS} FROM chat_users u WHERE {where} LIMIT 1")
        with self._engine.connect() as conn:
            row = conn.execute(sql, params).mappings().first()
        return _user_from_row(row) if row else None

    def get_user_by_email(self, email: str) -> UserRecord | None:
        return self._one_user("lower(u.email) = lower(:email)", {"email": email})

    def get_user(self, user_id: str) -> UserRecord | None:
        if not _is_uuid(user_id):
            return None
        return self._one_user("u.id = CAST(:id AS uuid)", {"id": user_id})

    def get_bot_user(self) -> UserRecord | None:
        return self._one_user("u.is_bot AND u.is_active ORDER BY u.created_at", {})

    def set_password(self, user_id: str, password_hash: str) -> None:
        from sqlalchemy import text

        with self._engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE chat_users SET password_hash = :h, must_change_password = false,"
                    " updated_at = now() WHERE id = CAST(:id AS uuid)"
                ),
                {"h": password_hash, "id": user_id},
            )
            # 비밀번호 변경 시 기존 refresh 세션 전부 폐기
            conn.execute(
                text(
                    "UPDATE chat_refresh_tokens SET revoked_at = now()"
                    " WHERE user_id = CAST(:id AS uuid) AND revoked_at IS NULL"
                ),
                {"id": user_id},
            )

    def create_refresh(self, user_id: str, token_hash: str, expires_at: datetime) -> None:
        from sqlalchemy import text

        with self._engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO chat_refresh_tokens (id, user_id, token_hash, expires_at)"
                    " VALUES (gen_random_uuid(), CAST(:uid AS uuid), :h, :exp)"
                ),
                {"uid": user_id, "h": token_hash, "exp": expires_at},
            )

    def consume_refresh(self, token_hash: str) -> str | None:
        """유효한 토큰이면 원자적으로 폐기(rotation)하고 user_id 를 반환한다."""
        from sqlalchemy import text

        with self._engine.begin() as conn:
            uid = conn.execute(
                text(
                    """
                    UPDATE chat_refresh_tokens t SET revoked_at = now()
                    FROM chat_users u
                    WHERE t.token_hash = :h AND t.revoked_at IS NULL AND t.expires_at > now()
                      AND u.id = t.user_id AND u.is_active
                    RETURNING t.user_id
                    """
                ),
                {"h": token_hash},
            ).scalar()
        return str(uid) if uid else None

    def revoke_refresh(self, token_hash: str) -> None:
        from sqlalchemy import text

        with self._engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE chat_refresh_tokens SET revoked_at = now()"
                    " WHERE token_hash = :h AND revoked_at IS NULL"
                ),
                {"h": token_hash},
            )

    # ------------------------------------------------------------ channels
    def list_member_channels(self, user_id: str) -> list[MemberChannel]:
        from sqlalchemy import text

        if not _is_uuid(user_id):
            return []
        sql = text(
            """
            SELECT c.id, c.name, c.display_name, c.type, c.purpose, m.role,
                   (SELECT count(*) FROM chat_posts p
                     WHERE p.channel_id = c.id AND p.delete_at IS NULL
                       AND (p.user_id IS NULL OR p.user_id <> m.user_id)
                       AND p.created_at > coalesce(m.last_viewed_at, 'epoch'::timestamptz)
                   ) AS unread
            FROM chat_channel_members m
            JOIN chat_channels c ON c.id = m.channel_id
            WHERE m.user_id = CAST(:uid AS uuid) AND c.archived_at IS NULL
            ORDER BY c.name
            """
        )
        with self._engine.connect() as conn:
            rows = conn.execute(sql, {"uid": user_id}).mappings().all()
        return [
            MemberChannel(
                channel=ChannelRecord(
                    id=str(r["id"]),
                    name=r["name"],
                    display_name=r["display_name"],
                    type=r["type"],
                    purpose=r["purpose"],
                ),
                role=r["role"],
                unread=int(r["unread"] or 0),
            )
            for r in rows
        ]

    def get_channel(self, id_or_name: str) -> ChannelRecord | None:
        from sqlalchemy import text

        if _is_uuid(id_or_name):
            where, params = "c.id = CAST(:v AS uuid)", {"v": id_or_name}
        else:
            where, params = "c.name = :v", {"v": id_or_name}
        sql = text(
            "SELECT c.id, c.name, c.display_name, c.type, c.purpose FROM chat_channels c"
            f" WHERE {where} AND c.archived_at IS NULL LIMIT 1"
        )
        with self._engine.connect() as conn:
            r = conn.execute(sql, params).mappings().first()
        if r is None:
            return None
        return ChannelRecord(
            id=str(r["id"]),
            name=r["name"],
            display_name=r["display_name"],
            type=r["type"],
            purpose=r["purpose"],
        )

    def get_member_role(self, channel_id: str, user_id: str) -> str | None:
        from sqlalchemy import text

        if not (_is_uuid(channel_id) and _is_uuid(user_id)):
            return None
        with self._engine.connect() as conn:
            role = conn.execute(
                text(
                    "SELECT role FROM chat_channel_members"
                    " WHERE channel_id = CAST(:c AS uuid) AND user_id = CAST(:u AS uuid)"
                ),
                {"c": channel_id, "u": user_id},
            ).scalar()
        return role

    def list_members(self, channel_id: str) -> list[UserRecord]:
        from sqlalchemy import text

        sql = text(
            f"SELECT {_USER_COLS} FROM chat_channel_members m JOIN chat_users u ON u.id = m.user_id"
            " WHERE m.channel_id = CAST(:c AS uuid) AND u.is_active ORDER BY u.display_name"
        )
        with self._engine.connect() as conn:
            rows = conn.execute(sql, {"c": channel_id}).mappings().all()
        return [_user_from_row(r) for r in rows]

    def mark_viewed(self, channel_id: str, user_id: str) -> None:
        from sqlalchemy import text

        with self._engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE chat_channel_members SET last_viewed_at = now()"
                    " WHERE channel_id = CAST(:c AS uuid) AND user_id = CAST(:u AS uuid)"
                ),
                {"c": channel_id, "u": user_id},
            )

    def get_binding(self, channel_id: str) -> ChannelBinding | None:
        from sqlalchemy import text

        if not _is_uuid(channel_id):
            return None
        sql = text(
            """
            SELECT b.id, c.id AS channel_id, c.name AS channel_name, b.mode, b.trigger_word,
                   b.enabled, b.history_turns, b.mention_user, b.ack_message_enabled,
                   b.feedback_enabled, b.direct_llm_enabled, ks.filter_json, ks.conversation_mode
            FROM channel_bindings b
            JOIN chat_channels c ON c.id = b.channel_ref
            LEFT JOIN knowledge_scopes ks ON ks.id = b.knowledge_scope_id
            WHERE c.id = CAST(:c AS uuid)
            ORDER BY b.enabled DESC, b.updated_at DESC
            LIMIT 1
            """
        )
        with self._engine.connect() as conn:
            row = conn.execute(sql, {"c": channel_id}).mappings().first()
        return _binding_from_row(row) if row else None

    # ------------------------------------------------------------ posts
    def _participants(self, conn: Any, root_ids: list[str]) -> dict[str, list[UserBrief]]:
        from sqlalchemy import text

        if not root_ids:
            return {}
        rows = (
            conn.execute(
                text(
                    """
                SELECT DISTINCT ON (r.root_id, u.id) r.root_id, u.id, u.display_name,
                       u.avatar_url, u.is_bot
                FROM chat_posts r JOIN chat_users u ON u.id = r.user_id
                WHERE r.root_id = ANY(CAST(:ids AS uuid[])) AND r.delete_at IS NULL
                """
                ),
                {"ids": root_ids},
            )
            .mappings()
            .all()
        )
        out: dict[str, list[UserBrief]] = {}
        for r in rows:
            out.setdefault(str(r["root_id"]), []).append(
                UserBrief(
                    id=str(r["id"]),
                    display_name=r["display_name"],
                    avatar_url=r["avatar_url"],
                    is_bot=r["is_bot"],
                )
            )
        return out

    def get_post(self, post_id: str) -> PostRow | None:
        from sqlalchemy import text

        if not _is_uuid(post_id):
            return None
        with self._engine.connect() as conn:
            row = (
                conn.execute(
                    text(_POST_SELECT + " WHERE p.id = CAST(:id AS uuid) AND p.delete_at IS NULL"),
                    {"id": post_id},
                )
                .mappings()
                .first()
            )
            if row is None:
                return None
            parts = self._participants(conn, [str(row["id"])])
        return _post_from_row(row, parts.get(str(row["id"])))

    def list_root_posts(
        self, channel_id: str, *, limit: int, before: str | None
    ) -> tuple[list[PostRow], bool]:
        from sqlalchemy import text

        params: dict[str, Any] = {"c": channel_id, "n": limit + 1}
        cond = ""
        if before and _is_uuid(before):
            cond = (
                " AND p.created_at < (SELECT created_at FROM chat_posts"
                " WHERE id = CAST(:before AS uuid))"
            )
            params["before"] = before
        sql = text(
            _POST_SELECT + " WHERE p.channel_id = CAST(:c AS uuid) AND p.root_id IS NULL"
            " AND p.delete_at IS NULL" + cond + " ORDER BY p.created_at DESC LIMIT :n"
        )
        with self._engine.connect() as conn:
            rows = conn.execute(sql, params).mappings().all()
            has_more = len(rows) > limit
            rows = list(rows[:limit])
            parts = self._participants(
                conn, [str(r["id"]) for r in rows if int(r["reply_count"] or 0) > 0]
            )
        posts = [_post_from_row(r, parts.get(str(r["id"]))) for r in reversed(rows)]
        return posts, has_more

    def list_replies(self, root_id: str) -> list[PostRow]:
        from sqlalchemy import text

        sql = text(
            _POST_SELECT
            + " WHERE p.root_id = CAST(:r AS uuid) AND p.delete_at IS NULL ORDER BY p.created_at"
        )
        with self._engine.connect() as conn:
            rows = conn.execute(sql, {"r": root_id}).mappings().all()
        return [_post_from_row(r) for r in rows]

    def thread_has_bot(self, root_id: str) -> bool:
        from sqlalchemy import text

        sql = text(
            """
            SELECT 1 FROM chat_posts p
            WHERE (p.id = CAST(:r AS uuid) OR p.root_id = CAST(:r AS uuid))
              AND p.type = 'bot' AND p.delete_at IS NULL
            LIMIT 1
            """
        )
        with self._engine.connect() as conn:
            return conn.execute(sql, {"r": root_id}).first() is not None

    @staticmethod
    def _insert_post(  # created_at=clock_timestamp(): 같은 트랜잭션의 질문→Bot 순서 보장 (now() 는 동일값)
        conn: Any,
        *,
        channel_id: str,
        root_id: str | None,
        user_id: str,
        type_: str,
        message: str,
        props: dict[str, Any],
        client_id: str | None,
    ) -> str:
        from sqlalchemy import text

        return str(
            conn.execute(
                text(
                    """
                    INSERT INTO chat_posts
                        (id, channel_id, root_id, user_id, type, message, props, client_id,
                         created_at)
                    VALUES (gen_random_uuid(), CAST(:c AS uuid), CAST(:r AS uuid),
                            CAST(:u AS uuid), :t, :m, CAST(:props AS jsonb), :cid,
                            clock_timestamp())
                    RETURNING id
                    """
                ),
                {
                    "c": channel_id,
                    "r": root_id,
                    "u": user_id,
                    "t": type_,
                    "m": message,
                    "props": json.dumps(props, ensure_ascii=False),
                    "cid": client_id,
                },
            ).scalar_one()
        )

    def create_post(
        self,
        *,
        channel_id: str,
        root_id: str | None,
        user: UserRecord,
        message: str,
        client_id: str | None,
    ) -> PostRow:
        with self._engine.begin() as conn:
            pid = self._insert_post(
                conn,
                channel_id=channel_id,
                root_id=root_id,
                user_id=user.id,
                type_="user",
                message=message,
                props={},
                client_id=client_id,
            )
        post = self.get_post(pid)
        assert post is not None
        return post

    def create_question(
        self,
        *,
        channel_id: str,
        root_id: str | None,
        user: UserRecord,
        message: str,
        client_id: str | None,
        bot: UserRecord,
        bot_root_id: str | None,
        bot_props: dict[str, Any],
    ) -> QuestionResult:
        """질문 Post + placeholder Bot Post + chat_jobs 를 단일 트랜잭션으로 생성 (§7.1.1 MUST)."""
        from sqlalchemy import text

        with self._engine.begin() as conn:
            pid = self._insert_post(
                conn,
                channel_id=channel_id,
                root_id=root_id,
                user_id=user.id,
                type_="user",
                message=message,
                props={},
                client_id=client_id,
            )
            bot_root = pid if bot_root_id == BOT_ROOT_SELF else bot_root_id
            bid = self._insert_post(
                conn,
                channel_id=channel_id,
                root_id=bot_root,
                user_id=bot.id,
                type_="bot",
                message="",
                props=bot_props,
                client_id=None,
            )
            job_id = conn.execute(
                text(
                    "INSERT INTO chat_jobs (id, post_id, bot_post_id, status)"
                    " VALUES (gen_random_uuid(), CAST(:p AS uuid), CAST(:b AS uuid), 'QUEUED')"
                    " RETURNING id"
                ),
                {"p": pid, "b": bid},
            ).scalar_one()
        user_post, bot_post = self.get_post(pid), self.get_post(bid)
        assert user_post is not None and bot_post is not None
        return QuestionResult(user_post=user_post, bot_post=bot_post, job_id=str(job_id))

    def update_post(
        self, post_id: str, *, message: str | None = None, props: dict[str, Any] | None = None
    ) -> PostRow | None:
        from sqlalchemy import text

        sets, params = [], {"id": post_id}
        if message is not None:
            sets.append("message = :m")
            params["m"] = message
        if props is not None:
            sets.append("props = props || CAST(:props AS jsonb)")
            params["props"] = json.dumps(props, ensure_ascii=False)
        if sets:
            with self._engine.begin() as conn:
                conn.execute(
                    text(
                        f"UPDATE chat_posts SET {', '.join(sets)}"
                        " WHERE id = CAST(:id AS uuid) AND delete_at IS NULL"
                    ),
                    params,
                )
        return self.get_post(post_id)

    def soft_delete_post(self, post_id: str) -> PostRow | None:
        from sqlalchemy import text

        post = self.get_post(post_id)
        if post is None:
            return None
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE chat_posts SET delete_at = now()"
                    " WHERE (id = CAST(:id AS uuid) OR root_id = CAST(:id AS uuid))"
                    " AND delete_at IS NULL"
                ),
                {"id": post_id},
            )
        return post

    def mark_job_failed(self, job_id: str, error: str) -> None:
        from sqlalchemy import text

        with self._engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE chat_jobs SET status = 'FAILED', error = :e, completed_at = now()"
                    " WHERE id = CAST(:id AS uuid)"
                ),
                {"e": error[:500], "id": job_id},
            )

    # ------------------------------------------------------------ feedback
    def get_answer_ref(self, bot_post_id: str) -> AnswerRef | None:
        from sqlalchemy import text

        if not _is_uuid(bot_post_id):
            return None
        sql = text(
            """
            SELECT m.id, c.channel_id
            FROM messages m
            JOIN channel_conversations c ON c.id = m.conversation_id
            WHERE m.post_id = CAST(:p AS uuid) AND m.role = 'assistant'
            LIMIT 1
            """
        )
        with self._engine.connect() as conn:
            row = conn.execute(sql, {"p": bot_post_id}).mappings().first()
        return (
            AnswerRef(message_id=str(row["id"]), channel_id=str(row["channel_id"])) if row else None
        )

    def upsert_feedback(
        self, message_id: str, user_id: str, value: FeedbackValue, channel_id: str
    ) -> None:
        from sqlalchemy import text

        sql = text(
            """
            INSERT INTO message_feedback (message_id, user_id, value, channel_id)
            VALUES (CAST(:mid AS uuid), :uid, :value, :cid)
            ON CONFLICT (message_id, user_id)
            DO UPDATE SET value = EXCLUDED.value,
                          channel_id = EXCLUDED.channel_id,
                          updated_at = now()
            """
        )
        with self._engine.begin() as conn:
            conn.execute(
                sql, {"mid": message_id, "uid": user_id, "value": value.value, "cid": channel_id}
            )

    def feedback_counts(self, message_id: str) -> dict[str, int]:
        from sqlalchemy import text

        sql = text(
            "SELECT value, count(*) AS n FROM message_feedback"
            " WHERE message_id = CAST(:mid AS uuid) GROUP BY value"
        )
        with self._engine.connect() as conn:
            rows = conn.execute(sql, {"mid": message_id}).all()
        counts = {r.value: int(r.n) for r in rows}
        return {"1": counts.get("UP", 0), "-1": counts.get("DOWN", 0)}


# --------------------------------------------------------------------------- #
# In-memory Fake (테스트용)
# --------------------------------------------------------------------------- #


@dataclass
class _Refresh:
    user_id: str
    expires_at: datetime
    revoked: bool = False


@dataclass
class InMemoryChatStore:
    users: dict[str, UserRecord] = field(default_factory=dict)
    channels: dict[str, ChannelRecord] = field(default_factory=dict)
    members: dict[tuple[str, str], str] = field(default_factory=dict)  # (channel, user) -> role
    bindings: dict[str, ChannelBinding] = field(default_factory=dict)
    posts: dict[str, PostRow] = field(default_factory=dict)
    jobs: list[dict[str, Any]] = field(default_factory=list)
    answers: dict[str, AnswerRef] = field(default_factory=dict)  # bot_post_id -> ref
    feedback: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)
    refresh: dict[str, _Refresh] = field(default_factory=dict)
    viewed: dict[tuple[str, str], datetime] = field(default_factory=dict)
    client_ids: set[tuple[str, str]] = field(default_factory=set)

    # users / auth
    def get_user_by_email(self, email: str) -> UserRecord | None:
        return next((u for u in self.users.values() if u.email.lower() == email.lower()), None)

    def get_user(self, user_id: str) -> UserRecord | None:
        return self.users.get(user_id)

    def get_bot_user(self) -> UserRecord | None:
        return next((u for u in self.users.values() if u.is_bot and u.is_active), None)

    def set_password(self, user_id: str, password_hash: str) -> None:
        u = self.users[user_id]
        u.password_hash, u.must_change_password = password_hash, False
        for r in self.refresh.values():
            if r.user_id == user_id:
                r.revoked = True

    def create_refresh(self, user_id: str, token_hash: str, expires_at: datetime) -> None:
        self.refresh[token_hash] = _Refresh(user_id=user_id, expires_at=expires_at)

    def consume_refresh(self, token_hash: str) -> str | None:
        r = self.refresh.get(token_hash)
        if r is None or r.revoked or r.expires_at <= _now():
            return None
        user = self.users.get(r.user_id)
        if user is None or not user.is_active:
            return None
        r.revoked = True
        return r.user_id

    def revoke_refresh(self, token_hash: str) -> None:
        if token_hash in self.refresh:
            self.refresh[token_hash].revoked = True

    # channels
    def list_member_channels(self, user_id: str) -> list[MemberChannel]:
        out = []
        for (cid, uid), role in self.members.items():
            if uid != user_id:
                continue
            seen = self.viewed.get((cid, uid))
            unread = sum(
                1
                for p in self.posts.values()
                if p.channel_id == cid
                and p.delete_at is None
                and (p.user is None or p.user.id != uid)
                and (seen is None or _as_dt(p.created_at) > seen)
            )
            out.append(MemberChannel(channel=self.channels[cid], role=role, unread=unread))
        return sorted(out, key=lambda m: m.channel.name)

    def get_channel(self, id_or_name: str) -> ChannelRecord | None:
        if id_or_name in self.channels:
            return self.channels[id_or_name]
        return next((c for c in self.channels.values() if c.name == id_or_name), None)

    def get_member_role(self, channel_id: str, user_id: str) -> str | None:
        return self.members.get((channel_id, user_id))

    def list_members(self, channel_id: str) -> list[UserRecord]:
        return [self.users[u] for (c, u) in self.members if c == channel_id]

    def mark_viewed(self, channel_id: str, user_id: str) -> None:
        self.viewed[(channel_id, user_id)] = _now()

    def get_binding(self, channel_id: str) -> ChannelBinding | None:
        return self.bindings.get(channel_id)

    # posts
    def _with_stats(self, p: PostRow) -> PostRow:
        replies = [r for r in self.posts.values() if r.root_id == p.id and r.delete_at is None]
        parts: dict[str, UserBrief] = {r.user.id: r.user for r in replies if r.user}
        return replace(
            p,
            reply_count=len(replies),
            last_reply_at=max((r.created_at for r in replies), default=None),
            participants=list(parts.values()),
        )

    def get_post(self, post_id: str) -> PostRow | None:
        p = self.posts.get(post_id)
        return self._with_stats(p) if p and p.delete_at is None else None

    def list_root_posts(
        self, channel_id: str, *, limit: int, before: str | None
    ) -> tuple[list[PostRow], bool]:
        roots = [
            p
            for p in self.posts.values()
            if p.channel_id == channel_id and p.root_id is None and p.delete_at is None
        ]
        roots.sort(key=lambda p: _as_dt(p.created_at))
        if before and before in self.posts:
            cut = _as_dt(self.posts[before].created_at)
            roots = [p for p in roots if _as_dt(p.created_at) < cut]
        has_more = len(roots) > limit
        return [self._with_stats(p) for p in roots[-limit:]], has_more

    def list_replies(self, root_id: str) -> list[PostRow]:
        rs = [p for p in self.posts.values() if p.root_id == root_id and p.delete_at is None]
        return sorted(rs, key=lambda p: _as_dt(p.created_at))

    def thread_has_bot(self, root_id: str) -> bool:
        return any(
            p.type == "bot" and p.delete_at is None and (p.id == root_id or p.root_id == root_id)
            for p in self.posts.values()
        )

    def _insert(self, *, channel_id, root_id, user: UserRecord, type_, message, props) -> PostRow:
        # 단조 증가 시각 (동일 tick 정렬 안정성)
        ts = _now() + timedelta(microseconds=len(self.posts))
        p = PostRow(
            id=str(uuid.uuid4()),
            channel_id=channel_id,
            root_id=root_id,
            type=type_,
            message=message,
            created_at=ts,
            props=dict(props),
            user=user.brief(),
        )
        self.posts[p.id] = p
        return p

    def _claim_client_id(self, user_id: str, client_id: str | None) -> None:
        if client_id is None:
            return
        if (user_id, client_id) in self.client_ids:  # (user_id, client_id) UNIQUE — 2차 방어선
            raise ValueError("duplicate client_id")
        self.client_ids.add((user_id, client_id))

    def create_post(
        self,
        *,
        channel_id: str,
        root_id: str | None,
        user: UserRecord,
        message: str,
        client_id: str | None,
    ) -> PostRow:
        self._claim_client_id(user.id, client_id)
        return self._with_stats(
            self._insert(
                channel_id=channel_id,
                root_id=root_id,
                user=user,
                type_="user",
                message=message,
                props={},
            )
        )

    def create_question(
        self,
        *,
        channel_id: str,
        root_id: str | None,
        user: UserRecord,
        message: str,
        client_id: str | None,
        bot: UserRecord,
        bot_root_id: str | None,
        bot_props: dict[str, Any],
    ) -> QuestionResult:
        self._claim_client_id(user.id, client_id)
        up = self._insert(
            channel_id=channel_id,
            root_id=root_id,
            user=user,
            type_="user",
            message=message,
            props={},
        )
        broot = up.id if bot_root_id == BOT_ROOT_SELF else bot_root_id
        bp = self._insert(
            channel_id=channel_id, root_id=broot, user=bot, type_="bot", message="", props=bot_props
        )
        job_id = str(uuid.uuid4())
        self.jobs.append({"id": job_id, "post_id": up.id, "bot_post_id": bp.id, "status": "QUEUED"})
        return QuestionResult(
            user_post=self._with_stats(up), bot_post=self._with_stats(bp), job_id=job_id
        )

    def update_post(
        self, post_id: str, *, message: str | None = None, props: dict[str, Any] | None = None
    ) -> PostRow | None:
        p = self.posts.get(post_id)
        if p is None or p.delete_at is not None:
            return None
        if message is not None:
            p.message = message
        if props is not None:
            p.props = {**p.props, **props}
        return self._with_stats(p)

    def soft_delete_post(self, post_id: str) -> PostRow | None:
        p = self.get_post(post_id)
        if p is None:
            return None
        for q in self.posts.values():
            if q.id == post_id or q.root_id == post_id:
                q.delete_at = _now()
        return p

    def mark_job_failed(self, job_id: str, error: str) -> None:
        for j in self.jobs:
            if j["id"] == job_id:
                j["status"], j["error"] = "FAILED", error

    # feedback
    def get_answer_ref(self, bot_post_id: str) -> AnswerRef | None:
        return self.answers.get(bot_post_id)

    def upsert_feedback(
        self, message_id: str, user_id: str, value: FeedbackValue, channel_id: str
    ) -> None:
        key = (message_id, user_id)
        if key in self.feedback:
            self.feedback[key]["value"] = value  # 재클릭 = 의견 변경 (행 수 유지)
        else:
            self.feedback[key] = {
                "message_id": message_id,
                "user_id": user_id,
                "value": value,
                "channel_id": channel_id,
            }

    def feedback_counts(self, message_id: str) -> dict[str, int]:
        vals = [f["value"] for (m, _), f in self.feedback.items() if m == message_id]
        return {"1": vals.count(FeedbackValue.UP), "-1": vals.count(FeedbackValue.DOWN)}


def _as_dt(v: datetime | str) -> datetime:
    return v if isinstance(v, datetime) else datetime.fromisoformat(v)
