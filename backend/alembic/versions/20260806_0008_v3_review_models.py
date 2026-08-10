"""V3 阶段 2A：工程审查数据模型、证据绑定和确定性规则基础设施。

新增：
- workspaces.review_template_key（nullable，engineering 可选，general 保持 null）
- review_runs 表
- evidences 表
- review_findings 表
- review_actions 表

Revision ID: 20260806_0008
Revises: 20260806_0007
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260806_0008"
down_revision: Union[str, None] = "20260806_0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Workspace 扩展：review_template_key
    with op.batch_alter_table("workspaces") as batch_op:
        batch_op.add_column(
            sa.Column("review_template_key", sa.String(120), nullable=True)
        )
        batch_op.create_check_constraint(
            "ck_workspaces_review_template_key",
            "review_template_key IS NULL OR review_template_key = 'engineering_bid_review_v1'",
        )

    # 2. ReviewRun
    op.create_table(
        "review_runs",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column("workspace_id", sa.Integer, sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("owner_user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("review_template_key", sa.String(120), nullable=False),
        sa.Column("status", sa.String(50), nullable=False, server_default="pending", index=True),
        sa.Column("rule_pack_id", sa.String(200), nullable=False),
        sa.Column("rule_pack_version", sa.String(50), nullable=False),
        sa.Column("rule_pack_hash", sa.String(64), nullable=False),
        sa.Column("rule_snapshot_json", sa.Text, nullable=False),
        sa.Column("input_snapshot_hash", sa.String(64), nullable=True),
        sa.Column("model_provider", sa.String(80), nullable=True),
        sa.Column("model_name", sa.String(120), nullable=True),
        sa.Column("prompt_version", sa.String(50), nullable=True),
        sa.Column("retrieval_snapshot_json", sa.Text, nullable=True),
        sa.Column("error_code", sa.String(80), nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("started_at", sa.DateTime, nullable=True),
        sa.Column("completed_at", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')",
            name="ck_review_runs_status",
        ),
    )

    # 3. Evidence
    op.create_table(
        "evidences",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column("review_run_id", sa.Integer, sa.ForeignKey("review_runs.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("workspace_id", sa.Integer, sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("owner_user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("file_id", sa.Integer, sa.ForeignKey("files.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("locator_type", sa.String(50), nullable=False),
        sa.Column("page_number", sa.Integer, nullable=True),
        sa.Column("sheet_name", sa.String(500), nullable=True),
        sa.Column("cell_range", sa.String(200), nullable=True),
        sa.Column("chunk_id", sa.Integer, nullable=True),
        sa.Column("quote", sa.String(2000), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("parser_name", sa.String(120), nullable=False),
        sa.Column("parser_version", sa.String(50), nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "locator_type IN ('pdf_page', 'spreadsheet_cell', 'text_chunk')",
            name="ck_evidences_locator_type",
        ),
    )

    # 4. ReviewFinding
    op.create_table(
        "review_findings",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column("review_run_id", sa.Integer, sa.ForeignKey("review_runs.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("workspace_id", sa.Integer, sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("owner_user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("issue_code", sa.String(120), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("category", sa.String(120), nullable=False),
        sa.Column("severity", sa.String(50), nullable=False),
        sa.Column("conclusion", sa.Text, nullable=False),
        sa.Column("suggestion", sa.Text, nullable=False),
        sa.Column("rule_id", sa.String(200), nullable=False),
        sa.Column("rule_version", sa.String(50), nullable=False),
        sa.Column("evidence_ids_json", sa.Text, nullable=False),
        sa.Column("status", sa.String(50), nullable=False, server_default="pending_review", index=True),
        sa.Column("source_step_id", sa.String(120), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("reviewed_at", sa.DateTime, nullable=True),
        sa.Column("reviewed_by", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("review_note", sa.Text, nullable=True),
        sa.CheckConstraint(
            "severity IN ('high', 'medium', 'low')",
            name="ck_review_findings_severity",
        ),
        sa.CheckConstraint(
            "status IN ('pending_review', 'confirmed', 'rejected', 'modified', 'resolved')",
            name="ck_review_findings_status",
        ),
    )

    # 5. ReviewAction
    op.create_table(
        "review_actions",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column("review_finding_id", sa.Integer, sa.ForeignKey("review_findings.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("review_run_id", sa.Integer, sa.ForeignKey("review_runs.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("workspace_id", sa.Integer, sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("owner_user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("action_type", sa.String(50), nullable=False),
        sa.Column("before_json", sa.Text, nullable=True),
        sa.Column("after_json", sa.Text, nullable=True),
        sa.Column("review_note", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "action_type IN ('confirm', 'reject', 'modify', 'resolve')",
            name="ck_review_actions_action_type",
        ),
    )


def downgrade() -> None:
    op.drop_table("review_actions")
    op.drop_table("review_findings")
    op.drop_table("evidences")
    op.drop_table("review_runs")

    with op.batch_alter_table("workspaces") as batch_op:
        batch_op.drop_constraint("ck_workspaces_review_template_key", type_="check")
        batch_op.drop_column("review_template_key")
