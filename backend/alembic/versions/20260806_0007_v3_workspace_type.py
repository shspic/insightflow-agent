"""V3 阶段 1：工作区类型分区（engineering / general）

Revision ID: 20260806_0007
Revises: 20260724_0006
Create Date: 2026-08-06
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260806_0007"
down_revision: Union[str, Sequence[str], None] = "20260724_0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("workspaces") as batch_op:
        batch_op.add_column(
            sa.Column(
                "workspace_type",
                sa.String(50),
                nullable=False,
                server_default="general",
            ),
        )
        batch_op.create_check_constraint(
            "ck_workspaces_workspace_type",
            "workspace_type IN ('engineering', 'general')",
        )
        batch_op.create_index(
            "ix_workspaces_workspace_type",
            ["workspace_type"],
        )


def downgrade() -> None:
    with op.batch_alter_table("workspaces") as batch_op:
        batch_op.drop_index("ix_workspaces_workspace_type")
        batch_op.drop_constraint("ck_workspaces_workspace_type", type_="check")
        batch_op.drop_column("workspace_type")
