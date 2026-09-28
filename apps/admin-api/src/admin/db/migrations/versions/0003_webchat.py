"""Mattermost 제거 → Web Chat(aiops_chatbot 이식) 스키마 — docs/TDD.md §5 (v2.0).

Revision ID: 0003_webchat
Revises: 0002_feedback_enabled
Create Date: 2026-09-28

데이터 보존 원칙:
- `mattermost_channels.id`(UUID) 를 그대로 `chat_channels.id` 로 재사용한다 → binding FK 유지.
- Mattermost channel_id 문자열로 저장돼 있던 참조(document_channel_acl / channel_conversations /
  message_feedback)는 새 chat_channels.id 로 재매핑한다.
  ⚠ Qdrant payload `allowed_channel_ids` 는 DB 가 아니므로 **업그레이드 후 전 문서 재색인 필요**
    (parser-indexer 가 document_channel_acl 을 다시 읽어 payload 를 갱신).
- 과거 Mattermost 대화(conversation/messages)는 감사·피드백 통계용으로 보존하되,
  scope_key 형식이 바뀌므로 신규 대화 이력에는 합류하지 않는다.
- 전달/수신 이벤트 테이블(mattermost_events / mattermost_deliveries)은 삭제한다.
"""

from __future__ import annotations

from alembic import op

revision = "0003_webchat"
down_revision = "0002_feedback_enabled"
branch_labels = None
depends_on = None

_UPGRADE_SQL = """
-- ---------------------------------------------------------------- channels
ALTER TABLE mattermost_channels RENAME TO chat_channels;
ALTER TABLE chat_channels ADD COLUMN name VARCHAR(80);
ALTER TABLE chat_channels ADD COLUMN type VARCHAR(20) NOT NULL DEFAULT 'public';
ALTER TABLE chat_channels ADD COLUMN purpose VARCHAR(500);
ALTER TABLE chat_channels ADD COLUMN created_at TIMESTAMPTZ NOT NULL DEFAULT now();
ALTER TABLE chat_channels ADD COLUMN archived_at TIMESTAMPTZ;

-- 기존 Mattermost channel_name → slug. 팀이 달라 이름이 겹치면 접미사로 유일화.
UPDATE chat_channels c SET name = sub.slug
FROM (
    SELECT id,
           CASE WHEN rn = 1 THEN base ELSE base || '-' || rn END AS slug
    FROM (
        SELECT id, base, row_number() OVER (PARTITION BY base ORDER BY id) AS rn
        FROM (
            SELECT id,
                   left(coalesce(nullif(regexp_replace(lower(channel_name),
                        '[^a-z0-9_-]+', '-', 'g'), ''), 'channel'), 70) AS base
            FROM chat_channels
        ) s0
    ) s1
) sub
WHERE c.id = sub.id;
UPDATE chat_channels SET display_name = coalesce(display_name, channel_name);

-- 채널 id 문자열 참조 재매핑 (Mattermost channel_id → chat_channels.id)
UPDATE document_channel_acl a SET channel_id = c.id::text
FROM chat_channels c WHERE a.channel_id = c.channel_id;
UPDATE channel_conversations v SET channel_id = c.id::text
FROM chat_channels c WHERE v.channel_id = c.channel_id AND v.team_id = c.team_id;
UPDATE message_feedback f SET channel_id = c.id::text
FROM chat_channels c WHERE f.channel_id = c.channel_id;

ALTER TABLE chat_channels DROP CONSTRAINT IF EXISTS mattermost_channels_team_id_channel_id_key;
ALTER TABLE chat_channels DROP COLUMN team_id;
ALTER TABLE chat_channels DROP COLUMN team_domain;
ALTER TABLE chat_channels DROP COLUMN channel_id;
ALTER TABLE chat_channels DROP COLUMN channel_name;
ALTER TABLE chat_channels ALTER COLUMN name SET NOT NULL;
ALTER TABLE chat_channels ALTER COLUMN display_name SET NOT NULL;
ALTER TABLE chat_channels ADD CONSTRAINT uq_chat_channels_name UNIQUE (name);
ALTER TABLE chat_channels ADD CONSTRAINT ck_chat_channels_type CHECK (type IN ('public', 'private'));

-- ---------------------------------------------------------------- bindings
ALTER TABLE mattermost_channel_bindings RENAME TO channel_bindings;
ALTER TABLE channel_bindings DROP COLUMN secret_ref;
ALTER TABLE channel_bindings DROP COLUMN secret_updated_at;
ALTER TABLE channel_bindings DROP CONSTRAINT IF EXISTS mattermost_channel_bindings_channel_ref_fkey;
ALTER TABLE channel_bindings ADD CONSTRAINT fk_bindings_channel
    FOREIGN KEY (channel_ref) REFERENCES chat_channels(id) ON DELETE CASCADE;
-- 채널당 binding 이 여럿일 수 있다(과거 데이터). 조회는 enabled 우선 · 최신 updated_at 1건.
CREATE INDEX idx_bindings_channel ON channel_bindings (channel_ref, enabled, updated_at DESC);

-- 제약/인덱스 이름에서 mattermost 접두어 제거
ALTER INDEX mattermost_channels_pkey RENAME TO chat_channels_pkey;
ALTER INDEX mattermost_channel_bindings_pkey RENAME TO channel_bindings_pkey;
ALTER TABLE channel_bindings RENAME CONSTRAINT mattermost_channel_bindings_knowledge_scope_id_fkey
    TO fk_bindings_knowledge_scope;

-- ---------------------------------------------------------------- users / auth
CREATE TABLE chat_users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(254) NOT NULL,
    display_name VARCHAR(200) NOT NULL,
    role VARCHAR(20) NOT NULL DEFAULT 'user' CHECK (role IN ('user', 'admin')),
    is_bot BOOLEAN NOT NULL DEFAULT false,
    is_active BOOLEAN NOT NULL DEFAULT true,
    password_hash VARCHAR(255),          -- scrypt(HMAC(pepper, prehash)). 원문/prehash 미저장
    must_change_password BOOLEAN NOT NULL DEFAULT true,
    avatar_url VARCHAR(500),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX uq_chat_users_email ON chat_users (lower(email));

CREATE TABLE chat_refresh_tokens (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES chat_users(id) ON DELETE CASCADE,
    token_hash VARCHAR(64) NOT NULL UNIQUE,  -- sha256(원문). 원문은 HttpOnly 쿠키에만
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_refresh_user ON chat_refresh_tokens (user_id) WHERE revoked_at IS NULL;

CREATE TABLE chat_channel_members (
    channel_id UUID NOT NULL REFERENCES chat_channels(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES chat_users(id) ON DELETE CASCADE,
    role VARCHAR(30) NOT NULL DEFAULT 'member' CHECK (role IN ('member', 'channel_admin')),
    last_viewed_at TIMESTAMPTZ,
    joined_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (channel_id, user_id)
);
CREATE INDEX idx_members_user ON chat_channel_members (user_id);

-- ---------------------------------------------------------------- posts
CREATE TABLE chat_posts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    channel_id UUID NOT NULL REFERENCES chat_channels(id) ON DELETE CASCADE,
    root_id UUID REFERENCES chat_posts(id) ON DELETE CASCADE,
    user_id UUID REFERENCES chat_users(id),
    type VARCHAR(10) NOT NULL CHECK (type IN ('user', 'bot', 'system')),
    message TEXT NOT NULL DEFAULT '',
    blocks JSONB,
    props JSONB NOT NULL DEFAULT '{}',
    client_id VARCHAR(64),               -- 클라이언트 멱등 키 (FR-WEB-006 2차 방어선)
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    edit_at TIMESTAMPTZ,
    delete_at TIMESTAMPTZ
);
CREATE INDEX idx_posts_channel ON chat_posts (channel_id, root_id, created_at DESC);
CREATE INDEX idx_posts_root ON chat_posts (root_id, created_at) WHERE root_id IS NOT NULL;
CREATE UNIQUE INDEX uq_posts_client ON chat_posts (user_id, client_id) WHERE client_id IS NOT NULL;

-- ---------------------------------------------------------------- jobs / delivery
DROP TABLE mattermost_deliveries;
ALTER TABLE chat_jobs DROP COLUMN event_id;
DROP TABLE mattermost_events;
ALTER TABLE chat_jobs ADD COLUMN post_id UUID REFERENCES chat_posts(id) ON DELETE SET NULL;
ALTER TABLE chat_jobs ADD COLUMN bot_post_id UUID REFERENCES chat_posts(id) ON DELETE SET NULL;
UPDATE chat_jobs SET status = 'DELIVERY_FAILED' WHERE status = 'DELIVERY_PENDING';

-- ---------------------------------------------------------------- conversations / messages
ALTER TABLE channel_conversations DROP COLUMN team_id;
-- 과거 Mattermost post id 문자열은 chat_posts 와 무관 → NULL (감사 목적 원문은 content 에 보존)
ALTER TABLE messages ALTER COLUMN mattermost_post_id TYPE UUID USING NULL;
ALTER TABLE messages RENAME COLUMN mattermost_post_id TO post_id;
ALTER TABLE messages ADD CONSTRAINT fk_messages_post
    FOREIGN KEY (post_id) REFERENCES chat_posts(id) ON DELETE SET NULL;
CREATE INDEX idx_messages_post ON messages (post_id) WHERE post_id IS NOT NULL;

ALTER TABLE message_feedback RENAME COLUMN mattermost_user_id TO user_id;
ALTER TABLE message_feedback RENAME CONSTRAINT message_feedback_message_id_mattermost_user_id_key
    TO uq_feedback_user;

-- ---------------------------------------------------------------- bot user
INSERT INTO chat_users (email, display_name, role, is_bot, must_change_password)
VALUES ('rag-assistant@bot.local', 'RAG Assistant', 'user', true, false);
"""


def upgrade() -> None:
    op.execute(_UPGRADE_SQL)


def downgrade() -> None:
    # Web Chat 데이터(사용자/Post)는 Mattermost 스키마로 되돌릴 수 없다 — 구조만 복원.
    op.execute(
        """
        ALTER TABLE message_feedback RENAME CONSTRAINT uq_feedback_user
            TO message_feedback_message_id_mattermost_user_id_key;
        ALTER TABLE message_feedback RENAME COLUMN user_id TO mattermost_user_id;
        ALTER TABLE messages DROP CONSTRAINT IF EXISTS fk_messages_post;
        DROP INDEX IF EXISTS idx_messages_post;
        ALTER TABLE messages RENAME COLUMN post_id TO mattermost_post_id;
        ALTER TABLE messages ALTER COLUMN mattermost_post_id TYPE VARCHAR(64) USING NULL;
        ALTER TABLE channel_conversations ADD COLUMN team_id VARCHAR(64) NOT NULL DEFAULT '';

        ALTER TABLE chat_jobs DROP COLUMN bot_post_id;
        ALTER TABLE chat_jobs DROP COLUMN post_id;
        CREATE TABLE mattermost_events (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            post_id VARCHAR(64) NOT NULL UNIQUE, root_id VARCHAR(64),
            team_id VARCHAR(64) NOT NULL, channel_id VARCHAR(64) NOT NULL,
            user_id VARCHAR(64) NOT NULL, payload_hash VARCHAR(80) NOT NULL,
            status VARCHAR(20) NOT NULL, reject_reason VARCHAR(100),
            received_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        ALTER TABLE chat_jobs ADD COLUMN event_id UUID REFERENCES mattermost_events(id);
        CREATE TABLE mattermost_deliveries (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            chat_job_id UUID NOT NULL REFERENCES chat_jobs(id),
            channel_id VARCHAR(64) NOT NULL, attempt INT NOT NULL DEFAULT 0,
            status VARCHAR(20) NOT NULL, http_status INT, error TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        DROP TABLE chat_posts;
        DROP TABLE chat_channel_members;
        DROP TABLE chat_refresh_tokens;
        DROP TABLE chat_users;

        DROP INDEX IF EXISTS idx_bindings_channel;
        ALTER TABLE channel_bindings RENAME CONSTRAINT fk_bindings_knowledge_scope
            TO mattermost_channel_bindings_knowledge_scope_id_fkey;
        ALTER INDEX channel_bindings_pkey RENAME TO mattermost_channel_bindings_pkey;
        ALTER INDEX chat_channels_pkey RENAME TO mattermost_channels_pkey;
        ALTER TABLE channel_bindings DROP CONSTRAINT IF EXISTS fk_bindings_channel;
        ALTER TABLE channel_bindings ADD COLUMN secret_ref VARCHAR(255) NOT NULL DEFAULT '';
        ALTER TABLE channel_bindings ADD COLUMN secret_updated_at TIMESTAMPTZ;
        ALTER TABLE channel_bindings RENAME TO mattermost_channel_bindings;

        ALTER TABLE chat_channels DROP CONSTRAINT IF EXISTS ck_chat_channels_type;
        ALTER TABLE chat_channels DROP CONSTRAINT IF EXISTS uq_chat_channels_name;
        ALTER TABLE chat_channels ADD COLUMN team_id VARCHAR(64) NOT NULL DEFAULT 'web';
        ALTER TABLE chat_channels ADD COLUMN team_domain VARCHAR(200);
        ALTER TABLE chat_channels ADD COLUMN channel_id VARCHAR(64);
        UPDATE chat_channels SET channel_id = id::text;
        ALTER TABLE chat_channels ALTER COLUMN channel_id SET NOT NULL;
        ALTER TABLE chat_channels RENAME COLUMN name TO channel_name;
        ALTER TABLE chat_channels DROP COLUMN type;
        ALTER TABLE chat_channels DROP COLUMN purpose;
        ALTER TABLE chat_channels DROP COLUMN created_at;
        ALTER TABLE chat_channels DROP COLUMN archived_at;
        ALTER TABLE chat_channels RENAME TO mattermost_channels;
        ALTER TABLE mattermost_channels ADD UNIQUE (team_id, channel_id);
        ALTER TABLE mattermost_channel_bindings ADD CONSTRAINT
            mattermost_channel_bindings_channel_ref_fkey
            FOREIGN KEY (channel_ref) REFERENCES mattermost_channels(id);
        """
    )
