"""新增 V2 认证安全字段和持久化限流表

Revision ID: 20260723_0003
Revises: 20260723_0002
Create Date: 2026-07-23
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260723_0003"
down_revision: Union[str, Sequence[str], None] = "20260723_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("auth_sessions") as batch_op:
        batch_op.add_column(sa.Column("csrf_token_hash", sa.String(length=255), nullable=True))

    with op.batch_alter_table("invite_codes") as batch_op:
        batch_op.drop_constraint("ck_invite_codes_status", type_="check")
        batch_op.create_check_constraint(
            "ck_invite_codes_status",
            "status IN ('active', 'disabled', 'exhausted', 'expired')",
        )

    with op.batch_alter_table("files") as batch_op:
        batch_op.add_column(sa.Column("mime_type", sa.String(length=150), nullable=True))
        batch_op.add_column(sa.Column("size_bytes", sa.Integer(), nullable=True))

    op.create_table(
        "auth_rate_limits",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("scope_type", sa.String(length=50), nullable=False),
        sa.Column("scope_hash", sa.String(length=64), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("window_started_at", sa.DateTime(), nullable=False),
        sa.Column("blocked_until", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("scope_type", "scope_hash", name="uq_auth_rate_limits_scope"),
    )
    op.create_index("ix_auth_rate_limits_id", "auth_rate_limits", ["id"], unique=False)
    op.create_index(
        "ix_auth_rate_limits_scope_type",
        "auth_rate_limits",
        ["scope_type"],
        unique=False,
    )
    op.create_index(
        "ix_auth_rate_limits_blocked_until",
        "auth_rate_limits",
        ["blocked_until"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_auth_rate_limits_blocked_until", table_name="auth_rate_limits")
    op.drop_index("ix_auth_rate_limits_scope_type", table_name="auth_rate_limits")
    op.drop_index("ix_auth_rate_limits_id", table_name="auth_rate_limits")
    op.drop_table("auth_rate_limits")

    with op.batch_alter_table("files") as batch_op:
        batch_op.drop_column("size_bytes")
        batch_op.drop_column("mime_type")

    op.execute(
        "UPDATE invite_codes SET status = 'active' "
        "WHERE status IN ('exhausted', 'expired')"
    )
    with op.batch_alter_table("invite_codes") as batch_op:
        batch_op.drop_constraint("ck_invite_codes_status", type_="check")
        batch_op.create_check_constraint(
            "ck_invite_codes_status",
            "status IN ('active', 'disabled')",
        )

    with op.batch_alter_table("auth_sessions") as batch_op:
        batch_op.drop_column("csrf_token_hash")
