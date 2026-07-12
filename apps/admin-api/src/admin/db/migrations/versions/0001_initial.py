"""initial schema — docs/TDD.md §5 DDL (literal Postgres).

Revision ID: 0001_initial
Revises:
Create Date: 2026-07-11
"""

from __future__ import annotations

from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


# §5의 Postgres DDL을 그대로 반영한다 (feedback_enabled는 rev 0002에서 추가).
_UPGRADE_SQL = """
CREATE TABLE admin_users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    login_id VARCHAR(100) UNIQUE NOT NULL,
    display_name VARCHAR(200) NOT NULL,
    department VARCHAR(200),
    status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE roles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(50) UNIQUE NOT NULL
);

CREATE TABLE user_roles (
    user_id UUID NOT NULL REFERENCES admin_users(id) ON DELETE CASCADE,
    role_id UUID NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    PRIMARY KEY (user_id, role_id)
);

CREATE TABLE mattermost_channels (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    team_id VARCHAR(64) NOT NULL,
    team_domain VARCHAR(200),
    channel_id VARCHAR(64) NOT NULL,
    channel_name VARCHAR(200) NOT NULL,
    display_name VARCHAR(200),
    UNIQUE (team_id, channel_id)
);

CREATE TABLE knowledge_scopes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(200) NOT NULL,
    filter_json JSONB NOT NULL DEFAULT '{}',
    conversation_mode VARCHAR(20) NOT NULL DEFAULT 'CHANNEL'
);

CREATE TABLE mattermost_channel_bindings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    channel_ref UUID NOT NULL REFERENCES mattermost_channels(id),
    mode VARCHAR(30) NOT NULL DEFAULT 'DEDICATED_CHANNEL',
    trigger_word VARCHAR(50),
    enabled BOOLEAN NOT NULL DEFAULT false,
    knowledge_scope_id UUID REFERENCES knowledge_scopes(id),
    history_turns INT NOT NULL DEFAULT 8,
    mention_user BOOLEAN NOT NULL DEFAULT true,
    ack_message_enabled BOOLEAN NOT NULL DEFAULT true,
    secret_ref VARCHAR(255) NOT NULL,
    secret_updated_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE mattermost_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    post_id VARCHAR(64) NOT NULL UNIQUE,
    root_id VARCHAR(64),
    team_id VARCHAR(64) NOT NULL,
    channel_id VARCHAR(64) NOT NULL,
    user_id VARCHAR(64) NOT NULL,
    payload_hash VARCHAR(80) NOT NULL,
    status VARCHAR(20) NOT NULL,
    reject_reason VARCHAR(100),
    received_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_mm_events_channel ON mattermost_events (channel_id, received_at DESC);

CREATE TABLE chat_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id UUID REFERENCES mattermost_events(id),
    conversation_id UUID,
    status VARCHAR(30) NOT NULL DEFAULT 'QUEUED',
    error TEXT,
    queued_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ
);
CREATE INDEX idx_chat_jobs_status ON chat_jobs (status, queued_at);

CREATE TABLE mattermost_deliveries (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chat_job_id UUID NOT NULL REFERENCES chat_jobs(id),
    channel_id VARCHAR(64) NOT NULL,
    attempt INT NOT NULL DEFAULT 0,
    status VARCHAR(20) NOT NULL,
    http_status INT,
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_deliveries_dlq ON mattermost_deliveries (status) WHERE status = 'DEAD_LETTER';

CREATE TABLE channel_conversations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scope_key VARCHAR(200) NOT NULL UNIQUE,
    team_id VARCHAR(64) NOT NULL,
    channel_id VARCHAR(64) NOT NULL,
    root_id VARCHAR(64),
    mode VARCHAR(20) NOT NULL DEFAULT 'CHANNEL',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE chat_jobs
    ADD CONSTRAINT fk_chat_jobs_conversation
    FOREIGN KEY (conversation_id) REFERENCES channel_conversations(id);

CREATE TABLE messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id UUID NOT NULL REFERENCES channel_conversations(id),
    mattermost_post_id VARCHAR(64),
    role VARCHAR(20) NOT NULL,
    content TEXT NOT NULL,
    latency_ms INT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_messages_conv ON messages (conversation_id, created_at DESC);

CREATE TABLE citations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    message_id UUID NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    chunk_id VARCHAR(120) NOT NULL,
    document_id UUID,
    score REAL,
    rank INT
);

CREATE TABLE message_feedback (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    message_id UUID NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    mattermost_user_id VARCHAR(64) NOT NULL,
    value VARCHAR(10) NOT NULL CHECK (value IN ('UP', 'DOWN')),
    channel_id VARCHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (message_id, mattermost_user_id)
);
CREATE INDEX idx_feedback_channel ON message_feedback (channel_id, created_at DESC);
CREATE INDEX idx_feedback_message ON message_feedback (message_id);

CREATE TABLE documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title VARCHAR(500) NOT NULL,
    category VARCHAR(100),
    department VARCHAR(200),
    security_level VARCHAR(30) NOT NULL DEFAULT 'INTERNAL',
    status VARCHAR(20) NOT NULL DEFAULT 'UPLOADED',
    active_version_id UUID,
    created_by UUID REFERENCES admin_users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE document_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    version INT NOT NULL,
    hash VARCHAR(80) NOT NULL,
    file_path VARCHAR(1000) NOT NULL,
    file_size BIGINT,
    status VARCHAR(30) NOT NULL DEFAULT 'UPLOADED',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (document_id, version)
);
CREATE INDEX idx_doc_versions_hash ON document_versions (hash);

CREATE TABLE document_channel_acl (
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    channel_id VARCHAR(64) NOT NULL,
    access_type VARCHAR(20) NOT NULL DEFAULT 'ALLOW',
    PRIMARY KEY (document_id, channel_id)
);

CREATE TABLE index_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_version_id UUID NOT NULL REFERENCES document_versions(id),
    status VARCHAR(30) NOT NULL DEFAULT 'PENDING',
    progress REAL NOT NULL DEFAULT 0,
    stage VARCHAR(30),
    chunk_count INT,
    vector_count INT,
    error TEXT,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE settings (
    key VARCHAR(200) PRIMARY KEY,
    value JSONB NOT NULL,
    version INT NOT NULL DEFAULT 1,
    updated_by UUID REFERENCES admin_users(id),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE audit_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    actor VARCHAR(200) NOT NULL,
    action VARCHAR(100) NOT NULL,
    target VARCHAR(500),
    result VARCHAR(20) NOT NULL,
    detail JSONB,
    ts TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_audit_ts ON audit_logs (ts DESC);
"""

_DOWNGRADE_SQL = """
DROP TABLE IF EXISTS audit_logs CASCADE;
DROP TABLE IF EXISTS settings CASCADE;
DROP TABLE IF EXISTS index_jobs CASCADE;
DROP TABLE IF EXISTS document_channel_acl CASCADE;
DROP TABLE IF EXISTS document_versions CASCADE;
DROP TABLE IF EXISTS documents CASCADE;
DROP TABLE IF EXISTS message_feedback CASCADE;
DROP TABLE IF EXISTS citations CASCADE;
DROP TABLE IF EXISTS messages CASCADE;
DROP TABLE IF EXISTS channel_conversations CASCADE;
DROP TABLE IF EXISTS mattermost_deliveries CASCADE;
DROP TABLE IF EXISTS chat_jobs CASCADE;
DROP TABLE IF EXISTS mattermost_events CASCADE;
DROP TABLE IF EXISTS mattermost_channel_bindings CASCADE;
DROP TABLE IF EXISTS knowledge_scopes CASCADE;
DROP TABLE IF EXISTS mattermost_channels CASCADE;
DROP TABLE IF EXISTS user_roles CASCADE;
DROP TABLE IF EXISTS roles CASCADE;
DROP TABLE IF EXISTS admin_users CASCADE;
"""


def upgrade() -> None:
    op.execute(_UPGRADE_SQL)


def downgrade() -> None:
    op.execute(_DOWNGRADE_SQL)
