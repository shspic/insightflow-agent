"""新增 V2 身份、工作区和审计数据基础

Revision ID: 20260723_0002
Revises: 20260723_0001
Create Date: 2026-07-23

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260723_0002"
down_revision: Union[str, Sequence[str], None] = "20260723_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(length=150), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("must_change_password", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("last_login_at", sa.DateTime(), nullable=True),
        sa.Column("password_changed_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint("role IN ('user', 'admin')", name="ck_users_role"),
        sa.CheckConstraint("status IN ('active', 'disabled')", name="ck_users_status"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_id", "users", ["id"], unique=False)
    op.create_index("ix_users_status", "users", ["status"], unique=False)
    op.create_index("ix_users_username", "users", ["username"], unique=True)

    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_auth_sessions_expires_at", "auth_sessions", ["expires_at"], unique=False)
    op.create_index("ix_auth_sessions_id", "auth_sessions", ["id"], unique=False)
    op.create_index("ix_auth_sessions_revoked_at", "auth_sessions", ["revoked_at"], unique=False)
    op.create_index("ix_auth_sessions_token_hash", "auth_sessions", ["token_hash"], unique=True)
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"], unique=False)

    op.create_table(
        "invite_codes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code_hash", sa.String(length=255), nullable=False),
        sa.Column("code_hint", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("max_uses", sa.Integer(), nullable=True),
        sa.Column("used_count", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("max_uses IS NULL OR max_uses > 0", name="ck_invite_codes_max_uses"),
        sa.CheckConstraint("status IN ('active', 'disabled')", name="ck_invite_codes_status"),
        sa.CheckConstraint("used_count >= 0", name="ck_invite_codes_used_count"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_invite_codes_code_hash", "invite_codes", ["code_hash"], unique=True)
    op.create_index(
        "ix_invite_codes_created_by_user_id",
        "invite_codes",
        ["created_by_user_id"],
        unique=False,
    )
    op.create_index("ix_invite_codes_expires_at", "invite_codes", ["expires_at"], unique=False)
    op.create_index("ix_invite_codes_id", "invite_codes", ["id"], unique=False)
    op.create_index("ix_invite_codes_status", "invite_codes", ["status"], unique=False)

    op.create_table(
        "password_reset_requests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("request_note", sa.Text(), nullable=True),
        sa.Column("admin_note", sa.Text(), nullable=True),
        sa.Column("requested_at", sa.DateTime(), nullable=False),
        sa.Column("handled_at", sa.DateTime(), nullable=True),
        sa.Column("handled_by_user_id", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'completed')",
            name="ck_password_reset_requests_status",
        ),
        sa.ForeignKeyConstraint(["handled_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_password_reset_requests_handled_by_user_id",
        "password_reset_requests",
        ["handled_by_user_id"],
        unique=False,
    )
    op.create_index("ix_password_reset_requests_id", "password_reset_requests", ["id"], unique=False)
    op.create_index(
        "ix_password_reset_requests_status",
        "password_reset_requests",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_password_reset_requests_user_id",
        "password_reset_requests",
        ["user_id"],
        unique=False,
    )

    op.create_table(
        "workspaces",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("owner_user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint("status IN ('active', 'archived')", name="ck_workspaces_status"),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_workspaces_deleted_at", "workspaces", ["deleted_at"], unique=False)
    op.create_index("ix_workspaces_id", "workspaces", ["id"], unique=False)
    op.create_index("ix_workspaces_owner_user_id", "workspaces", ["owner_user_id"], unique=False)
    op.create_index("ix_workspaces_status", "workspaces", ["status"], unique=False)

    op.create_table(
        "workspace_files",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("workspace_id", sa.Integer(), nullable=False),
        sa.Column("file_id", sa.Integer(), nullable=False),
        sa.Column("file_role", sa.String(length=80), nullable=True),
        sa.Column("user_confirmed_role", sa.String(length=80), nullable=True),
        sa.Column("tags_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["file_id"], ["files.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "file_id", name="uq_workspace_files_workspace_file"),
    )
    op.create_index("ix_workspace_files_file_id", "workspace_files", ["file_id"], unique=False)
    op.create_index("ix_workspace_files_id", "workspace_files", ["id"], unique=False)
    op.create_index(
        "ix_workspace_files_workspace_id",
        "workspace_files",
        ["workspace_id"],
        unique=False,
    )

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(length=120), nullable=False),
        sa.Column("resource_type", sa.String(length=80), nullable=True),
        sa.Column("resource_id", sa.String(length=120), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("details_json", sa.Text(), nullable=True),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_logs_action", "audit_logs", ["action"], unique=False)
    op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"], unique=False)
    op.create_index("ix_audit_logs_id", "audit_logs", ["id"], unique=False)
    op.create_index("ix_audit_logs_resource_type", "audit_logs", ["resource_type"], unique=False)
    op.create_index("ix_audit_logs_status", "audit_logs", ["status"], unique=False)
    op.create_index("ix_audit_logs_user_id", "audit_logs", ["user_id"], unique=False)

    with op.batch_alter_table("files") as batch_op:
        batch_op.add_column(sa.Column("owner_user_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_files_owner_user_id_users",
            "users",
            ["owner_user_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index("ix_files_owner_user_id", ["owner_user_id"], unique=False)

    with op.batch_alter_table("tasks") as batch_op:
        batch_op.add_column(sa.Column("owner_user_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("workspace_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_tasks_owner_user_id_users",
            "users",
            ["owner_user_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_foreign_key(
            "fk_tasks_workspace_id_workspaces",
            "workspaces",
            ["workspace_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index("ix_tasks_owner_user_id", ["owner_user_id"], unique=False)
        batch_op.create_index("ix_tasks_workspace_id", ["workspace_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("tasks") as batch_op:
        batch_op.drop_index("ix_tasks_workspace_id")
        batch_op.drop_index("ix_tasks_owner_user_id")
        batch_op.drop_constraint("fk_tasks_workspace_id_workspaces", type_="foreignkey")
        batch_op.drop_constraint("fk_tasks_owner_user_id_users", type_="foreignkey")
        batch_op.drop_column("workspace_id")
        batch_op.drop_column("owner_user_id")

    with op.batch_alter_table("files") as batch_op:
        batch_op.drop_index("ix_files_owner_user_id")
        batch_op.drop_constraint("fk_files_owner_user_id_users", type_="foreignkey")
        batch_op.drop_column("owner_user_id")

    op.drop_index("ix_audit_logs_user_id", table_name="audit_logs")
    op.drop_index("ix_audit_logs_status", table_name="audit_logs")
    op.drop_index("ix_audit_logs_resource_type", table_name="audit_logs")
    op.drop_index("ix_audit_logs_id", table_name="audit_logs")
    op.drop_index("ix_audit_logs_created_at", table_name="audit_logs")
    op.drop_index("ix_audit_logs_action", table_name="audit_logs")
    op.drop_table("audit_logs")

    op.drop_index("ix_workspace_files_workspace_id", table_name="workspace_files")
    op.drop_index("ix_workspace_files_id", table_name="workspace_files")
    op.drop_index("ix_workspace_files_file_id", table_name="workspace_files")
    op.drop_table("workspace_files")

    op.drop_index("ix_workspaces_status", table_name="workspaces")
    op.drop_index("ix_workspaces_owner_user_id", table_name="workspaces")
    op.drop_index("ix_workspaces_id", table_name="workspaces")
    op.drop_index("ix_workspaces_deleted_at", table_name="workspaces")
    op.drop_table("workspaces")

    op.drop_index("ix_password_reset_requests_user_id", table_name="password_reset_requests")
    op.drop_index("ix_password_reset_requests_status", table_name="password_reset_requests")
    op.drop_index("ix_password_reset_requests_id", table_name="password_reset_requests")
    op.drop_index(
        "ix_password_reset_requests_handled_by_user_id",
        table_name="password_reset_requests",
    )
    op.drop_table("password_reset_requests")

    op.drop_index("ix_invite_codes_status", table_name="invite_codes")
    op.drop_index("ix_invite_codes_id", table_name="invite_codes")
    op.drop_index("ix_invite_codes_expires_at", table_name="invite_codes")
    op.drop_index("ix_invite_codes_created_by_user_id", table_name="invite_codes")
    op.drop_index("ix_invite_codes_code_hash", table_name="invite_codes")
    op.drop_table("invite_codes")

    op.drop_index("ix_auth_sessions_user_id", table_name="auth_sessions")
    op.drop_index("ix_auth_sessions_token_hash", table_name="auth_sessions")
    op.drop_index("ix_auth_sessions_revoked_at", table_name="auth_sessions")
    op.drop_index("ix_auth_sessions_id", table_name="auth_sessions")
    op.drop_index("ix_auth_sessions_expires_at", table_name="auth_sessions")
    op.drop_table("auth_sessions")

    op.drop_index("ix_users_username", table_name="users")
    op.drop_index("ix_users_status", table_name="users")
    op.drop_index("ix_users_id", table_name="users")
    op.drop_table("users")
