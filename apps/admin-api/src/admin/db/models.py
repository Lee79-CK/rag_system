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


# ===== Web Chat (aiops_chatbot 이식, Alembic rev.3) =====
class ChatUser(Base):
    """Web Chat 사용자. password_hash = scrypt(HMAC(pepper, prehash)) — 원문/prehash 미저장."""

    __tablename__ = "chat_users"

    id: Mapped[uuid.UUID] = _pk()
    email: Mapped[str] = mapped_column(String(254), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="user")
    is_bot: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    password_hash: Mapped[str | None] = mapped_column(String(255))
    must_change_password: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    avatar_url: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime.datetime] = _now_col(nullable=False)
    updated_at: Mapped[datetime.datetime] = _now_col(nullable=False, onupdate=func.now())


class ChatRefreshToken(Base):
    __tablename__ = "chat_refresh_tokens"

    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("chat_users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime.datetime] = _now_col(nullable=False)


class ChatChannel(Base):
    __tablename__ = "chat_channels"
    __table_args__ = (
        CheckConstraint("type IN ('public', 'private')", name="ck_chat_channels_type"),
    )

    id: Mapped[uuid.UUID] = _pk()
    name: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    type: Mapped[str] = mapped_column(String(20), nullable=False, default="public")
    purpose: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime.datetime] = _now_col(nullable=False)
    archived_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))

    bindings: Mapped[list[ChannelBindingRow]] = relationship(back_populates="channel")


class ChatChannelMember(Base):
    __tablename__ = "chat_channel_members"

    channel_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("chat_channels.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("chat_users.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str] = mapped_column(String(30), nullable=False, default="member")
    last_viewed_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    joined_at: Mapped[datetime.datetime] = _now_col(nullable=False)

    user: Mapped[ChatUser] = relationship()


class ChatPost(Base):
    __tablename__ = "chat_posts"

    id: Mapped[uuid.UUID] = _pk()
    channel_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("chat_channels.id", ondelete="CASCADE"), nullable=False
    )
    root_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("chat_posts.id", ondelete="CASCADE")
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("chat_users.id"))
    type: Mapped[str] = mapped_column(String(10), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    blocks: Mapped[list | None] = mapped_column(JsonB)
    props: Mapped[dict] = mapped_column(JsonB, nullable=False, default=dict)
    client_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime.datetime] = _now_col(nullable=False)
    edit_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    delete_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))


class KnowledgeScopeRow(Base):
    __tablename__ = "knowledge_scopes"

    id: Mapped[uuid.UUID] = _pk()
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    filter_json: Mapped[dict] = mapped_column(JsonB, nullable=False, default=dict)
    conversation_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="CHANNEL")


class ChannelBindingRow(Base):
    """채널 ↔ RAG 설정. 채널당 여러 행 가능 — 조회는 enabled 우선·최신 1건 (§7.1.1)."""

    __tablename__ = "channel_bindings"

    id: Mapped[uuid.UUID] = _pk()
    channel_ref: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("chat_channels.id", ondelete="CASCADE"), nullable=False
    )
    mode: Mapped[str] = mapped_column(String(30), nullable=False, default="DEDICATED_CHANNEL")
    trigger_word: Mapped[str | None] = mapped_column(String(50))
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    knowledge_scope_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("knowledge_scopes.id"))
    history_turns: Mapped[int] = mapped_column(Integer, nullable=False, default=8)
    mention_user: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    ack_message_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # v1.1 (Alembic rev.2): Channel별 피드백 on/off.
    feedback_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # v2.1 (Alembic 0004): `/` 접두어 LLM 직접 대화(RAG 미경유) 허용.
    direct_llm_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime.datetime] = _now_col(nullable=False)
    updated_at: Mapped[datetime.datetime] = _now_col(nullable=False, onupdate=func.now())

    channel: Mapped[ChatChannel] = relationship(back_populates="bindings")
    knowledge_scope: Mapped[KnowledgeScopeRow | None] = relationship()


class ChatJob(Base):
    __tablename__ = "chat_jobs"

    id: Mapped[uuid.UUID] = _pk()
    post_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("chat_posts.id", ondelete="SET NULL")
    )
    bot_post_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("chat_posts.id", ondelete="SET NULL")
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("channel_conversations.id")
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="QUEUED")
    error: Mapped[str | None] = mapped_column(Text)
    queued_at: Mapped[datetime.datetime] = _now_col(nullable=False)
    started_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))


# ===== 대화 =====
class ChannelConversation(Base):
    __tablename__ = "channel_conversations"

    id: Mapped[uuid.UUID] = _pk()
    scope_key: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
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
    # user 질문 Post / assistant = Bot Post (피드백 검증 시 Post→message 역조회)
    post_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("chat_posts.id", ondelete="SET NULL")
    )
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
        UniqueConstraint("message_id", "user_id", name="uq_feedback_user"),
        CheckConstraint("value IN ('UP', 'DOWN')", name="ck_feedback_value"),
    )

    id: Mapped[uuid.UUID] = _pk()
    message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)  # chat_users.id
    value: Mapped[str] = mapped_column(String(10), nullable=False)
    channel_id: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime.datetime] = _now_col(nullable=False)
    updated_at: Mapped[datetime.datetime] = _now_col(nullable=False, onupdate=func.now())

    message: Mapped[Message] = relationship(back_populates="feedback")


class EvaluationCandidate(Base):
    """👎 답변 → 평가셋 후보 (§13.3, Alembic 0005). 질문·답변은 승격 시점 스냅샷 — 원본 메시지가 지워져도 남는다."""

    __tablename__ = "evaluation_candidates"
    __table_args__ = (
        UniqueConstraint("message_id", name="uq_eval_candidate_message"),
        CheckConstraint(
            "status IN ('PENDING', 'ACCEPTED', 'REJECTED')", name="ck_eval_candidate_status"
        ),
    )

    id: Mapped[uuid.UUID] = _pk()
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL")
    )
    channel_id: Mapped[str] = mapped_column(String(64), nullable=False)  # chat_channels.id
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    cited_documents: Mapped[list] = mapped_column(JsonB, nullable=False, default=list)
    # 평가자가 채우는 정답(ground_truth) — §13.3
    case_type: Mapped[str] = mapped_column(String(20), nullable=False, default="single_doc")
    answer_gist: Mapped[str] = mapped_column(Text, nullable=False, default="")
    expected_documents: Mapped[list] = mapped_column(JsonB, nullable=False, default=list)
    expected_pages: Mapped[list] = mapped_column(JsonB, nullable=False, default=list)
    answerable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    note: Mapped[str | None] = mapped_column(Text)
    promoted_by: Mapped[str] = mapped_column(String(100), nullable=False)  # admin_users.login_id
    created_at: Mapped[datetime.datetime] = _now_col(nullable=False)
    updated_at: Mapped[datetime.datetime] = _now_col(nullable=False, onupdate=func.now())


class EvaluationRun(Base):
    """포털 평가 실행 (FR-OPS-008, Alembic 0006). 채택 후보로 rag-api 동기 completions 를 호출해 지표를 낸다."""

    __tablename__ = "evaluation_runs"
    __table_args__ = (
        CheckConstraint("status IN ('RUNNING', 'COMPLETED', 'FAILED')", name="ck_eval_run_status"),
    )

    id: Mapped[uuid.UUID] = _pk()
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="RUNNING")
    dataset: Mapped[str] = mapped_column(String(100), nullable=False, default="feedback-candidates")
    total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    done: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    metrics: Mapped[dict | None] = mapped_column(JsonB)  # rag_eval.MetricSummary
    error: Mapped[str | None] = mapped_column(Text)
    started_by: Mapped[str] = mapped_column(String(100), nullable=False)  # admin_users.login_id
    created_at: Mapped[datetime.datetime] = _now_col(nullable=False)
    # 진행 heartbeat — 문항마다 갱신. 오래 멈춘 RUNNING 은 조회 시 FAILED 로 정리한다.
    updated_at: Mapped[datetime.datetime] = _now_col(nullable=False, onupdate=func.now())
    completed_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))

    results: Mapped[list[EvaluationRunResult]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="EvaluationRunResult.seq"
    )


class EvaluationRunResult(Base):
    __tablename__ = "evaluation_run_results"

    id: Mapped[uuid.UUID] = _pk()
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("evaluation_runs.id", ondelete="CASCADE"), nullable=False
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    candidate_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("evaluation_candidates.id", ondelete="SET NULL")
    )
    case_id: Mapped[str] = mapped_column(String(40), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    case_type: Mapped[str] = mapped_column(String(20), nullable=False)
    answerable: Mapped[bool] = mapped_column(Boolean, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False, default="")
    insufficient_evidence: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    expected_documents: Mapped[list] = mapped_column(JsonB, nullable=False, default=list)
    citations: Mapped[list] = mapped_column(JsonB, nullable=False, default=list)  # 문서 제목
    retrieved: Mapped[list] = mapped_column(JsonB, nullable=False, default=list)  # 문서 제목
    recall_at_10: Mapped[float | None] = mapped_column(Float)
    citation_precision: Mapped[float | None] = mapped_column(Float)
    no_answer_safe: Mapped[float | None] = mapped_column(Float)
    answerable_answered: Mapped[float | None] = mapped_column(Float)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)

    run: Mapped[EvaluationRun] = relationship(back_populates="results")


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
    channel_id: Mapped[str] = mapped_column(String(64), primary_key=True)  # chat_channels.id
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
