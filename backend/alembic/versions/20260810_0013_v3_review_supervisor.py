"""阶段 5B：工程 Supervisor 两张表（review_supervisor_runs / review_supervisor_steps）。

Revision ID: 20260810_0013
Revises: 20260808_0012
Create Date: 2026-08-10

review_supervisor_steps.retry_of_id 自引用 FK（ondelete SET NULL）；
supervisor_run_id/workspace 等 FK ondelete CASCADE（workspace 永久删除级联清除）。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260810_0013"
down_revision: str | None = "20260808_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "review_supervisor_runs",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("owner_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("review_run_id", sa.Integer(), sa.ForeignKey("review_runs.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="planning", index=True),
        sa.Column("input_state_hash", sa.String(length=64), nullable=False, index=True),
        sa.Column("graph_version", sa.String(length=50), nullable=False),
        sa.Column("quality_gate_version", sa.String(length=50), nullable=False),
        sa.Column("current_step", sa.String(length=50), nullable=True),
        sa.Column("max_step_retries", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("verification_run_id", sa.Integer(), sa.ForeignKey("review_verification_runs.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("report_id", sa.Integer(), sa.ForeignKey("review_reports.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("quality_gate_json", sa.Text(), nullable=True),
        sa.Column("clarification_json", sa.Text(), nullable=True),
        sa.Column("error_code", sa.String(length=120), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "status IN ('planning', 'running', 'ready_to_report', 'completed', "
            "'completed_with_warnings', 'needs_human', 'failed')",
            name="ck_review_supervisor_runs_status",
        ),
    )
    op.create_table(
        "review_supervisor_steps",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("supervisor_run_id", sa.Integer(), sa.ForeignKey("review_supervisor_runs.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("owner_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("review_run_id", sa.Integer(), sa.ForeignKey("review_runs.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("step_id", sa.String(length=120), nullable=False),
        sa.Column("node_name", sa.String(length=50), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("retry_of_id", sa.Integer(), sa.ForeignKey("review_supervisor_steps.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="running", index=True),
        sa.Column("input_json", sa.Text(), nullable=True),
        sa.Column("output_json", sa.Text(), nullable=True),
        sa.Column("reused", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("error_code", sa.String(length=120), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "node_name IN ('extraction', 'verification', 'quality_review', 'reporting')",
            name="ck_review_supervisor_steps_node",
        ),
        sa.CheckConstraint(
            "status IN ('running', 'success', 'failed', 'skipped', 'needs_human')",
            name="ck_review_supervisor_steps_status",
        ),
    )


def downgrade() -> None:
    op.drop_table("review_supervisor_steps")
    op.drop_table("review_supervisor_runs")
