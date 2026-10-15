"""evaluation_candidates — 👎 답변 평가셋 후보 승격 (TDD §7.5, §13.3).

Revision ID: 0005_eval_candidates
Revises: 0004_direct_llm
Create Date: 2026-10-15
"""

from __future__ import annotations

from alembic import op

revision = "0005_eval_candidates"
down_revision = "0004_direct_llm"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
CREATE TABLE evaluation_candidates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    message_id UUID REFERENCES messages(id) ON DELETE SET NULL,
    channel_id VARCHAR(64) NOT NULL,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    cited_documents JSONB NOT NULL DEFAULT '[]'::jsonb,
    case_type VARCHAR(20) NOT NULL DEFAULT 'single_doc',
    answer_gist TEXT NOT NULL DEFAULT '',
    expected_documents JSONB NOT NULL DEFAULT '[]'::jsonb,
    expected_pages JSONB NOT NULL DEFAULT '[]'::jsonb,
    answerable BOOLEAN NOT NULL DEFAULT true,
    status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
    note TEXT,
    promoted_by VARCHAR(100) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_eval_candidate_message UNIQUE (message_id),
    CONSTRAINT ck_eval_candidate_status CHECK (status IN ('PENDING', 'ACCEPTED', 'REJECTED'))
);
CREATE INDEX idx_eval_candidates_status ON evaluation_candidates (status, created_at DESC);
"""
    )


def downgrade() -> None:
    op.execute("DROP TABLE evaluation_candidates")
