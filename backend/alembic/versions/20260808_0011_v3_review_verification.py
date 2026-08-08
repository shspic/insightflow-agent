"""阶段 4C-2：工程 Verification Agent 两张表（review_verification_runs / review_tool_calls）。

Revision ID: 20260808_0011
Revises: 20260807_0010
Create Date: 2026-08-08

review_tool_calls.retry_of_id 自引用 FK（ondelete SET NULL），
其余 FK 均 ondelete CASCADE（workspace 永久删除时级联清除）。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260808_0011"
down_revision: str | None = "20260807_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "review_verification_runs",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("owner_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("review_run_id", sa.Integer(), sa.ForeignKey("review_runs.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="planning", index=True),
        sa.Column("input_state_hash", sa.String(length=64), nullable=False, index=True),
        sa.Column("plan_json", sa.Text(), nullable=True),
        sa.Column("planner_type", sa.String(length=50), nullable=False, server_default="deterministic"),
        sa.Column("fallback_used", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("fallback_reason", sa.String(length=500), nullable=True),
        sa.Column("model_provider", sa.String(length=80), nullable=True),
        sa.Column("model_name", sa.String(length=120), nullable=True),
        sa.Column("prompt_version", sa.String(length=50), nullable=True),
        sa.Column("token_usage_json", sa.Text(), nullable=True),
        sa.Column("tool_budget", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("tool_calls_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("candidate_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("warning_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "status IN ('planning', 'running', 'completed', "
            "'completed_with_warnings', 'failed')",
            name="ck_review_verification_runs_status",
        ),
    )
    op.create_table(
        "review_tool_calls",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("verification_run_id", sa.Integer(), sa.ForeignKey("review_verification_runs.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("review_run_id", sa.Integer(), sa.ForeignKey("review_runs.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("review_finding_id", sa.Integer(), sa.ForeignKey("review_findings.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("owner_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("node_name", sa.String(length=120), nullable=True),
        sa.Column("tool_name", sa.String(length=120), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("retry_of_id", sa.Integer(), sa.ForeignKey("review_tool_calls.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="running", index=True),
        sa.Column("input_json", sa.Text(), nullable=True),
        sa.Column("output_json", sa.Text(), nullable=True),
        sa.Column("error_code", sa.String(length=120), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("index_sha256", sa.String(length=64), nullable=True),
        sa.Column("corpus_sha256", sa.String(length=64), nullable=True),
        sa.Column("model_revision", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "status IN ('running', 'success', 'failed')",
            name="ck_review_tool_calls_status",
        ),
    )


def downgrade() -> None:
    op.drop_table("review_tool_calls")
    op.drop_table("review_verification_runs")
