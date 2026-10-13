"""add direct_llm_enabled to channel_bindings — `/` 접두어 LLM 직접 대화 (FR-CHAT-014, TDD §7.1.1).

Revision ID: 0004_direct_llm
Revises: 0003_webchat
Create Date: 2026-10-13
"""

from __future__ import annotations

from alembic import op

revision = "0004_direct_llm"
down_revision = "0003_webchat"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 기존 채널은 꺼진 상태로 시작 — 문서 근거 없는 답변은 관리자가 채널별로 명시적으로 켠다.
    op.execute(
        "ALTER TABLE channel_bindings ADD COLUMN direct_llm_enabled BOOLEAN NOT NULL DEFAULT false"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE channel_bindings DROP COLUMN direct_llm_enabled")
