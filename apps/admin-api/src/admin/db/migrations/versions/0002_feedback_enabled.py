"""add feedback_enabled to mattermost_channel_bindings — docs/TDD.md §7.2.5 (v1.1).

Revision ID: 0002_feedback_enabled
Revises: 0001_initial
Create Date: 2026-07-11
"""

from __future__ import annotations

from alembic import op

revision = "0002_feedback_enabled"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE mattermost_channel_bindings "
        "ADD COLUMN feedback_enabled BOOLEAN NOT NULL DEFAULT true"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE mattermost_channel_bindings DROP COLUMN feedback_enabled")
