"""V3 阶段 3B-1：独立工程审查报告与导出资产。

Revision ID: 20260807_0010
Revises: 20260806_0009
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260807_0010"
down_revision: Union[str, None] = "20260806_0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "review_reports",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column(
            "workspace_id",
            sa.Integer,
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "owner_user_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "review_run_id",
            sa.Integer,
            sa.ForeignKey("review_runs.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("status", sa.String(50), nullable=False, index=True),
        sa.Column("review_state_hash", sa.String(64), nullable=False, index=True),
        sa.Column("review_snapshot_json", sa.Text, nullable=False),
        sa.Column("quality_gate_json", sa.Text, nullable=False),
        sa.Column("warning_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("finding_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("high_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("medium_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("low_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("confirmed_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("rejected_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("modified_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("resolved_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("pending_review_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("generator_name", sa.String(120), nullable=False),
        sa.Column("generator_version", sa.String(50), nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "review_run_id", "version", name="uq_review_reports_run_version"
        ),
        sa.UniqueConstraint(
            "review_run_id",
            "review_state_hash",
            name="uq_review_reports_run_state_hash",
        ),
        sa.CheckConstraint(
            "status IN ('ready', 'ready_with_warnings')",
            name="ck_review_reports_status",
        ),
    )

    op.create_table(
        "review_report_assets",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column(
            "review_report_id",
            sa.Integer,
            sa.ForeignKey("review_reports.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "workspace_id",
            sa.Integer,
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "owner_user_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("asset_type", sa.String(30), nullable=False, index=True),
        sa.Column("file_name", sa.String(255), nullable=False),
        sa.Column("storage_path", sa.String(500), nullable=False),
        sa.Column("mime_type", sa.String(150), nullable=False),
        sa.Column("size_bytes", sa.Integer, nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "review_report_id", "asset_type", name="uq_review_report_assets_type"
        ),
        sa.CheckConstraint(
            "asset_type IN ('markdown', 'pdf')",
            name="ck_review_report_assets_type",
        ),
    )


def downgrade() -> None:
    op.drop_table("review_report_assets")
    op.drop_table("review_reports")
