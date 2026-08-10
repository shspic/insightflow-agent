"""阶段 4C-3：候选证据人工决策审计表（review_candidate_decisions）。

Revision ID: 20260808_0012
Revises: 20260808_0011
Create Date: 2026-08-08

- 唯一约束 (review_tool_call_id, candidate_rank)：同一候选只允许一次最终决策；
- decision 白名单 accept/reject；
- evidence_id ondelete SET NULL：Evidence 单独删除时保留审计行；
- 其余 FK 均 ondelete CASCADE：workspace 永久删除时级联清除。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260808_0012"
down_revision: str | None = "20260808_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "review_candidate_decisions",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("verification_run_id", sa.Integer(), sa.ForeignKey("review_verification_runs.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("review_tool_call_id", sa.Integer(), sa.ForeignKey("review_tool_calls.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("review_finding_id", sa.Integer(), sa.ForeignKey("review_findings.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("review_run_id", sa.Integer(), sa.ForeignKey("review_runs.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("owner_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("candidate_rank", sa.Integer(), nullable=False),
        sa.Column("candidate_chunk_id", sa.String(length=64), nullable=False),
        sa.Column("candidate_content_hash", sa.String(length=64), nullable=False),
        sa.Column("decision", sa.String(length=20), nullable=False),
        sa.Column("candidate_snapshot_json", sa.Text(), nullable=False),
        sa.Column("evidence_id", sa.Integer(), sa.ForeignKey("evidences.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "decision IN ('accept', 'reject')",
            name="ck_review_candidate_decisions_decision",
        ),
        sa.UniqueConstraint(
            "review_tool_call_id",
            "candidate_rank",
            name="uq_review_candidate_decisions_call_rank",
        ),
    )


def downgrade() -> None:
    op.drop_table("review_candidate_decisions")
