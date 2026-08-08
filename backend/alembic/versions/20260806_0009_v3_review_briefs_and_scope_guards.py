"""V3 阶段 2A 补修：ReviewBrief + ReviewRun Brief 绑定 + Workspace 模板约束修复。

Revision ID: 20260806_0009
Revises: 20260806_0008
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260806_0009"
down_revision: Union[str, None] = "20260806_0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. 创建 review_briefs 表
    op.create_table(
        "review_briefs",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column("workspace_id", sa.Integer, sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("owner_user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("raw_requirements", sa.Text, nullable=False),
        sa.Column("interpreted_json", sa.Text, nullable=False),
        sa.Column("status", sa.String(50), nullable=False, server_default="draft", index=True),
        sa.Column("interpreter_type", sa.String(50), nullable=False, server_default="deterministic_fixture"),
        sa.Column("model_provider", sa.String(80), nullable=True),
        sa.Column("model_name", sa.String(120), nullable=True),
        sa.Column("prompt_version", sa.String(50), nullable=True),
        sa.Column("clarification_questions_json", sa.Text, nullable=True),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("confirmed_at", sa.DateTime, nullable=True),
        sa.Column("confirmed_by", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.UniqueConstraint("workspace_id", "version", name="uq_review_briefs_workspace_version"),
        sa.CheckConstraint(
            "status IN ('draft', 'needs_clarification', 'confirmed', 'superseded')",
            name="ck_review_briefs_status",
        ),
    )

    # 2. ReviewRun 增加 Brief 快照字段
    with op.batch_alter_table("review_runs") as batch_op:
        batch_op.add_column(sa.Column("review_brief_id", sa.Integer, nullable=True))
        batch_op.add_column(sa.Column("review_brief_version", sa.Integer, nullable=True))
        batch_op.add_column(sa.Column("review_brief_hash", sa.String(64), nullable=True))
        batch_op.add_column(sa.Column("review_brief_snapshot_json", sa.Text, nullable=True))
        batch_op.create_foreign_key(
            "fk_review_runs_review_brief_id",
            "review_briefs",
            ["review_brief_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index("ix_review_runs_review_brief_id", ["review_brief_id"])

    # 3. 替换 Workspace 模板 CHECK：增加 workspace_type 条件
    with op.batch_alter_table("workspaces") as batch_op:
        batch_op.drop_constraint("ck_workspaces_review_template_key", type_="check")
        batch_op.create_check_constraint(
            "ck_workspaces_review_template_key",
            "review_template_key IS NULL OR (workspace_type = 'engineering' AND review_template_key = 'engineering_bid_review_v1')",
        )


def downgrade() -> None:
    # 恢复 0008 原有约束
    with op.batch_alter_table("workspaces") as batch_op:
        batch_op.drop_constraint("ck_workspaces_review_template_key", type_="check")
        batch_op.create_check_constraint(
            "ck_workspaces_review_template_key",
            "review_template_key IS NULL OR review_template_key = 'engineering_bid_review_v1'",
        )

    # 删除 ReviewRun Brief 字段
    with op.batch_alter_table("review_runs") as batch_op:
        batch_op.drop_index("ix_review_runs_review_brief_id")
        batch_op.drop_constraint("fk_review_runs_review_brief_id", type_="foreignkey")
        batch_op.drop_column("review_brief_snapshot_json")
        batch_op.drop_column("review_brief_hash")
        batch_op.drop_column("review_brief_version")
        batch_op.drop_column("review_brief_id")

    # 删除 review_briefs 表
    op.drop_table("review_briefs")
