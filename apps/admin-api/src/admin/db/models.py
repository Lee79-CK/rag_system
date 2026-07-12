"""SQLAlchemy 2.0 ORM — docs/TDD.md §5 DDL과 1:1 매핑.

PORTABILITY (§7.5 지시):
- UUID PK는 Python-side `default=uuid.uuid4` (server_default gen_random_uuid() 대신).
- 시각은 `DateTime(timezone=True)` + `default=func.now()`.
- JSONB는 `JSON().with_variant(JSONB, "postgresql")` — SQLite 단위테스트 / Postgres 운영 동시 지원.
"""

from __future__ import annotations

import datetime
import uuid

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# JSONB on Postgres, generic JSON elsewhere (SQLite for unit tests).
JsonB = JSON().with_variant(JSONB, "postgresql")


class Base(DeclarativeBase):
    pass


def _pk() -> Mapped[uuid.UUID]:
    return mapped_column(Uuid, primary_key=True, default=uuid.uuid4)


def _now_col(**kw: object) -> Mapped[datetime.datetime]:
    return mapped_column(DateTime(timezone=True), default=func.now(), **kw)  # type: ignore[arg-type]


# ===== Admin / RBAC =====
class AdminUser(Base):
    __tablename__ = "admin_users"

    id: Mapped[uuid.UUID] = _pk()
    login_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    department: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")
    created_at: Mapped[datetime.datetime] = _now_col(nullable=False)

    roles: Mapped[list[Role]] = relationship(
        secondary="user_roles", back_populates="users", lazy="selectin"
    )


class Role(Base):
    __tablename__ = "roles"

    id: Mapped[uuid.UUID] = _pk()
    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)

    users: Mapped[list[AdminUser]] = relationship(secondary="user_roles", back_populates="roles")


class UserRole(Base):
    __tablename__ = "user_roles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("admin_users.id", ondelete="CASCADE"), primary_key=True
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True
    )


# ===== Mattermost 연계 =====
class MattermostChannel(Base):
    __tablename__ = "mattermost_channels"
    __table_args__ = (UniqueConstraint("team_id", "channel_id", name="uq_mm_channel"),)

    id: Mapped[uuid.UUID] = _pk()
    team_id: Mapped[str] = mapped_column(String(64), nullable=False)
    team_domain: Mapped[str | None] = mapped_column(String(200))
    channel_id: Mapped[str] = mapped_column(String(64), nullable=False)
    channel_name: Mapped[str] = mapped_column(String(200), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(200))

    bindings: Mapped[list[MattermostChannelBinding]] = relationship(back_populates="channel")


class KnowledgeScopeRow(Base):
    __tablename__ = "knowledge_scopes"

    id: Mapped[uuid.UUID] = _pk()
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    filter_json: Mapped[dict] = mapped_column(JsonB, nullable=False, default=dict)
    conversation_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="CHANNEL")


class MattermostChannelBinding(Base):
    __tablename__ = "mattermost_channel_bindings"

    id: Mapped[uuid.UUID] = _pk()
    channel_ref: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("mattermost_channels.id"), nullable=False
    )
    mode: Mapped[str] = mapped_column(String(30), nullable=False, default="DEDICATED_CHANNEL")
    trigger_word: Mapped[str | None] = mapped_column(String(50))
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    knowledge_scope_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("knowledge_scopes.id"))
    history_turns: Mapped[int] = mapped_column(Integer, nullable=False, default=8)
    mention_user: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    ack_message_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # secret_ref: K8s Secret 이름만 저장 (NFR-SEC-006). 값(URL) 저장 금지.
    secret_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    secret_updated_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    # v1.1 (Alembic rev.2): Channel별 피드백 on/off.
    feedback_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime.datetime] = _now_col(nullable=False)
    updated_at: Mapped[datetime.datetime] = _now_col(nullable=False, onupdate=func.now())

    channel: Mapped[MattermostChannel] = relationship(back_populates="bindings")
    knowledge_scope: Mapped[KnowledgeScopeRow | None] = relationship()


class MattermostEvent(Base):
    __tablename__ = "mattermost_events"

    id: Mapped[uuid.UUID] = _pk()
    post_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    root_id: Mapped[str | None] = mapped_column(String(64))
    team_id: Mapped[str] = mapped_column(String(64), nullable=False)
    channel_id: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    reject_reason: Mapped[str | None] = mapped_column(String(100))
    received_at: Mapped[datetime.datetime] = _now_col(nullable=False)


class ChatJob(Base):
    __tablename__ = "chat_jobs"

    id: Mapped[uuid.UUID] = _pk()
    event_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("mattermost_events.id"))
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("channel_conversations.id")
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="QUEUED")
    error: Mapped[str | None] = mapped_column(Text)
    queued_at: Mapped[datetime.datetime] = _now_col(nullable=False)
    started_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))

    deliveries: Mapped[list[MattermostDelivery]] = relationship(back_populates="chat_job")


class MattermostDelivery(Base):
    __tablename__ = "mattermost_deliveries"

    id: Mapped[uuid.UUID] = _pk()
    chat_job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("chat_jobs.id"), nullable=False)
    channel_id: Mapped[str] = mapped_column(String(64), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    http_status: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime.datetime] = _now_col(nullable=False)
    updated_at: Mapped[datetime.datetime] = _now_col(nullable=False, onupdate=func.now())

    chat_job: Mapped[ChatJob] = relationship(back_populates="deliveries")


# ===== 대화 =====
class ChannelConversation(Base):
    __tablename__ = "channel_conversations"

    id: Mapped[uuid.UUID] = _pk()
    scope_key: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    team_id: Mapped[str] = mapped_column(String(64), nullable=False)
    channel_id: Mapped[str] = mapped_column(String(64), nullable=False)
    root_id: Mapped[str | None] = mapped_column(String(64))
    mode: Mapped[str] = mapped_column(String(20), nullable=False, default="CHANNEL")
    created_at: Mapped[datetime.datetime] = _now_col(nullable=False)

    messages: Mapped[list[Message]] = relationship(back_populates="conversation")


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = _pk()
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("channel_conversations.id"), nullable=False
    )
    mattermost_post_id: Mapped[str | None] = mapped_column(String(64))
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime.datetime] = _now_col(nullable=False)

    conversation: Mapped[ChannelConversation] = relationship(back_populates="messages")
    citations: Mapped[list[Citation]] = relationship(
        back_populates="message", cascade="all, delete-orphan"
    )
    feedback: Mapped[list[MessageFeedbackRow]] = relationship(
        back_populates="message", cascade="all, delete-orphan"
    )


class Citation(Base):
    __tablename__ = "citations"

    id: Mapped[uuid.UUID] = _pk()
    message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), nullable=False
    )
    chunk_id: Mapped[str] = mapped_column(String(120), nullable=False)
    document_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    score: Mapped[float | None] = mapped_column(Float)
    rank: Mapped[int | None] = mapped_column(Integer)

    message: Mapped[Message] = relationship(back_populates="citations")


class MessageFeedbackRow(Base):
    __tablename__ = "message_feedback"
    __table_args__ = (
        UniqueConstraint("message_id", "mattermost_user_id", name="uq_feedback_user"),
        CheckConstraint("value IN ('UP', 'DOWN')", name="ck_feedback_value"),
    )

    id: Mapped[uuid.UUID] = _pk()
    message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), nullable=False
    )
    mattermost_user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    value: Mapped[str] = mapped_column(String(10), nullable=False)
    channel_id: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime.datetime] = _now_col(nullable=False)
    updated_at: Mapped[datetime.datetime] = _now_col(nullable=False, onupdate=func.now())

    message: Mapped[Message] = relationship(back_populates="feedback")


# ===== 문서 =====
class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = _pk()
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    category: Mapped[str | None] = mapped_column(String(100))
    department: Mapped[str | None] = mapped_column(String(200))
    security_level: Mapped[str] = mapped_column(String(30), nullable=False, default="INTERNAL")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="UPLOADED")
    active_version_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("admin_users.id"))
    created_at: Mapped[datetime.datetime] = _now_col(nullable=False)
    updated_at: Mapped[datetime.datetime] = _now_col(nullable=False, onupdate=func.now())

    versions: Mapped[list[DocumentVersion]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class DocumentVersion(Base):
    __tablename__ = "document_versions"
    __table_args__ = (UniqueConstraint("document_id", "version", name="uq_doc_version"),)

    id: Mapped[uuid.UUID] = _pk()
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    hash: Mapped[str] = mapped_column(String(80), nullable=False)
    file_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    file_size: Mapped[int | None] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="UPLOADED")
    created_at: Mapped[datetime.datetime] = _now_col(nullable=False)

    document: Mapped[Document] = relationship(back_populates="versions")


class DocumentChannelAcl(Base):
    __tablename__ = "document_channel_acl"

    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True
    )
    channel_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    access_type: Mapped[str] = mapped_column(String(20), nullable=False, default="ALLOW")


class IndexJob(Base):
    __tablename__ = "index_jobs"

    id: Mapped[uuid.UUID] = _pk()
    document_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_versions.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="PENDING")
    progress: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    stage: Mapped[str | None] = mapped_column(String(30))
    chunk_count: Mapped[int | None] = mapped_column(Integer)
    vector_count: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime.datetime] = _now_col(nullable=False)


# ===== 운영 =====
class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(200), primary_key=True)
    value: Mapped[dict] = mapped_column(JsonB, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("admin_users.id"))
    updated_at: Mapped[datetime.datetime] = _now_col(nullable=False, onupdate=func.now())


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = _pk()
    actor: Mapped[str] = mapped_column(String(200), nullable=False)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    target: Mapped[str | None] = mapped_column(String(500))
    result: Mapped[str] = mapped_column(String(20), nullable=False)
    detail: Mapped[dict | None] = mapped_column(JsonB)
    ts: Mapped[datetime.datetime] = _now_col(nullable=False)
