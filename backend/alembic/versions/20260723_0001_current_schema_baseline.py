"""建立当前四张核心表的迁移基线

Revision ID: 20260723_0001
Revises:
Create Date: 2026-07-23

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260723_0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "files",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("file_type", sa.String(length=50), nullable=True),
        sa.Column("file_path", sa.String(length=500), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("schema_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_files_id", "files", ["id"], unique=False)

    op.create_table(
        "tasks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_input", sa.Text(), nullable=False),
        sa.Column("task_type", sa.String(length=80), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("file_ids_json", sa.Text(), nullable=True),
        sa.Column("final_answer", sa.Text(), nullable=True),
        sa.Column("report_path", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tasks_id", "tasks", ["id"], unique=False)

    op.create_table(
        "file_chunks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("file_id", sa.Integer(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("chunk_text", sa.Text(), nullable=False),
        sa.Column("vector_id", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["file_id"], ["files.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_file_chunks_file_id", "file_chunks", ["file_id"], unique=False)
    op.create_index("ix_file_chunks_id", "file_chunks", ["id"], unique=False)

    op.create_table(
        "tool_calls",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=True),
        sa.Column("node_name", sa.String(length=120), nullable=True),
        sa.Column("tool_name", sa.String(length=120), nullable=True),
        sa.Column("input_json", sa.Text(), nullable=True),
        sa.Column("output_json", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tool_calls_id", "tool_calls", ["id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_tool_calls_id", table_name="tool_calls")
    op.drop_table("tool_calls")
    op.drop_index("ix_file_chunks_id", table_name="file_chunks")
    op.drop_index("ix_file_chunks_file_id", table_name="file_chunks")
    op.drop_table("file_chunks")
    op.drop_index("ix_tasks_id", table_name="tasks")
    op.drop_table("tasks")
    op.drop_index("ix_files_id", table_name="files")
    op.drop_table("files")
