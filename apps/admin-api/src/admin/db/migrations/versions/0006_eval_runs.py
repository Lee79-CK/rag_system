"""evaluation_runs / evaluation_run_results — 포털 평가 실행·결과 (FR-OPS-008, TDD §7.5).

Revision ID: 0006_eval_runs
Revises: 0005_eval_candidates
Create Date: 2026-10-15
"""

from __future__ import annotations

from alembic import op

revision = "0006_eval_runs"
down_revision = "0005_eval_candidates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
CREATE TABLE evaluation_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    status VARCHAR(20) NOT NULL DEFAULT 'RUNNING',
    dataset VARCHAR(100) NOT NULL DEFAULT 'feedback-candidates',
    total INT NOT NULL DEFAULT 0,
    done INT NOT NULL DEFAULT 0,
    metrics JSONB,
    error TEXT,
    started_by VARCHAR(100) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,
    CONSTRAINT ck_eval_run_status CHECK (status IN ('RUNNING', 'COMPLETED', 'FAILED'))
);
CREATE INDEX idx_eval_runs_created ON evaluation_runs (created_at DESC);
-- 동시 실행 1건 (admin-api replica 가 여럿이어도 RUNNING 은 하나)
CREATE UNIQUE INDEX uq_eval_runs_single_running ON evaluation_runs ((true)) WHERE status = 'RUNNING';

CREATE TABLE evaluation_run_results (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID NOT NULL REFERENCES evaluation_runs(id) ON DELETE CASCADE,
    seq INT NOT NULL,
    candidate_id UUID REFERENCES evaluation_candidates(id) ON DELETE SET NULL,
    case_id VARCHAR(40) NOT NULL,
    question TEXT NOT NULL,
    case_type VARCHAR(20) NOT NULL,
    answerable BOOLEAN NOT NULL,
    answer TEXT NOT NULL DEFAULT '',
    insufficient_evidence BOOLEAN NOT NULL DEFAULT false,
    expected_documents JSONB NOT NULL DEFAULT '[]'::jsonb,
    citations JSONB NOT NULL DEFAULT '[]'::jsonb,
    retrieved JSONB NOT NULL DEFAULT '[]'::jsonb,
    recall_at_10 DOUBLE PRECISION,
    citation_precision DOUBLE PRECISION,
    no_answer_safe DOUBLE PRECISION,
    answerable_answered DOUBLE PRECISION,
    latency_ms INT,
    error TEXT
);
CREATE INDEX idx_eval_run_results_run ON evaluation_run_results (run_id, seq);
"""
    )


def downgrade() -> None:
    op.execute("DROP TABLE evaluation_run_results")
    op.execute("DROP TABLE evaluation_runs")
