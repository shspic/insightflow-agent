"""新增 V2 文件理解、关系和处理运行记录

Revision ID: 20260723_0004
Revises: 20260723_0003
Create Date: 2026-07-23

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260723_0004"
down_revision: Union[str, Sequence[str], None] = "20260723_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "file_profiles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("file_id", sa.Integer(), nullable=False),
        sa.Column("workspace_id", sa.Integer(), nullable=False),
        sa.Column("owner_user_id", sa.Integer(), nullable=False),
        sa.Column("profile_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("file_category", sa.String(length=50), nullable=True),
        sa.Column("detected_mime_type", sa.String(length=150), nullable=True),
        sa.Column("language", sa.String(length=50), nullable=True),
        sa.Column("title", sa.String(length=500), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("structure_json", sa.Text(), nullable=True),
        sa.Column("statistics_json", sa.Text(), nullable=True),
        sa.Column("quality_issues_json", sa.Text(), nullable=True),
        sa.Column("suggested_role", sa.String(length=80), nullable=True),
        sa.Column("confirmed_role", sa.String(length=80), nullable=True),
        sa.Column("tags_json", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("parser_name", sa.String(length=120), nullable=True),
        sa.Column("parser_version", sa.String(length=50), nullable=True),
        sa.Column("model_provider", sa.String(length=80), nullable=True),
        sa.Column("model_name", sa.String(length=120), nullable=True),
        sa.Column("prompt_version", sa.String(length=50), nullable=True),
        sa.Column("model_latency_ms", sa.Integer(), nullable=True),
        sa.Column("fallback_used", sa.Boolean(), nullable=False),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_file_profiles_confidence",
        ),
        sa.CheckConstraint(
            "status IN ('validating', 'parsing', 'profiling', 'ready', 'failed', 'unsupported')",
            name="ck_file_profiles_status",
        ),
        sa.ForeignKeyConstraint(["file_id"], ["files.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "file_id",
            "profile_version",
            name="uq_file_profiles_workspace_file_version",
        ),
    )
    op.create_index("ix_file_profiles_file_id", "file_profiles", ["file_id"], unique=False)
    op.create_index("ix_file_profiles_id", "file_profiles", ["id"], unique=False)
    op.create_index(
        "ix_file_profiles_owner_user_id",
        "file_profiles",
        ["owner_user_id"],
        unique=False,
    )
    op.create_index("ix_file_profiles_status", "file_profiles", ["status"], unique=False)
    op.create_index(
        "ix_file_profiles_workspace_id",
        "file_profiles",
        ["workspace_id"],
        unique=False,
    )

    op.create_table(
        "file_relations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("workspace_id", sa.Integer(), nullable=False),
        sa.Column("owner_user_id", sa.Integer(), nullable=False),
        sa.Column("source_file_id", sa.Integer(), nullable=False),
        sa.Column("target_file_id", sa.Integer(), nullable=False),
        sa.Column("relation_type", sa.String(length=80), nullable=False),
        sa.Column("direction", sa.String(length=40), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("evidence_json", sa.Text(), nullable=True),
        sa.Column("suggested_by", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("user_note", sa.Text(), nullable=True),
        sa.Column("supersedes_relation_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_file_relations_confidence",
        ),
        sa.CheckConstraint(
            "direction IN ('source_to_target', 'target_to_source', 'bidirectional')",
            name="ck_file_relations_direction",
        ),
        sa.CheckConstraint(
            "source_file_id != target_file_id",
            name="ck_file_relations_distinct_files",
        ),
        sa.CheckConstraint(
            "status IN ('suggested', 'confirmed', 'rejected', 'superseded')",
            name="ck_file_relations_status",
        ),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["source_file_id"],
            ["files.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_relation_id"],
            ["file_relations.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["target_file_id"],
            ["files.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_file_relations_id", "file_relations", ["id"], unique=False)
    op.create_index(
        "ix_file_relations_owner_user_id",
        "file_relations",
        ["owner_user_id"],
        unique=False,
    )
    op.create_index(
        "ix_file_relations_relation_type",
        "file_relations",
        ["relation_type"],
        unique=False,
    )
    op.create_index(
        "ix_file_relations_source_file_id",
        "file_relations",
        ["source_file_id"],
        unique=False,
    )
    op.create_index("ix_file_relations_status", "file_relations", ["status"], unique=False)
    op.create_index(
        "ix_file_relations_target_file_id",
        "file_relations",
        ["target_file_id"],
        unique=False,
    )
    op.create_index(
        "ix_file_relations_workspace_id",
        "file_relations",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        "ix_file_relations_workspace_status_confidence",
        "file_relations",
        ["workspace_id", "status", "confidence"],
        unique=False,
    )
    op.create_index(
        "uq_file_relations_current_direction_type",
        "file_relations",
        [
            "workspace_id",
            "source_file_id",
            "target_file_id",
            "relation_type",
            "direction",
        ],
        unique=True,
        sqlite_where=sa.text("status != 'superseded'"),
        postgresql_where=sa.text("status != 'superseded'"),
    )

    op.create_table(
        "file_processing_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("file_id", sa.Integer(), nullable=False),
        sa.Column("workspace_id", sa.Integer(), nullable=False),
        sa.Column("owner_user_id", sa.Integer(), nullable=False),
        sa.Column("profile_id", sa.Integer(), nullable=True),
        sa.Column("stage", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("processor", sa.String(length=120), nullable=False),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("used_model", sa.Boolean(), nullable=False),
        sa.Column("fallback_used", sa.Boolean(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "status IN ('running', 'success', 'failed', 'unsupported')",
            name="ck_file_processing_runs_status",
        ),
        sa.ForeignKeyConstraint(["file_id"], ["files.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["file_profiles.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_file_processing_runs_file_id",
        "file_processing_runs",
        ["file_id"],
        unique=False,
    )
    op.create_index(
        "ix_file_processing_runs_id",
        "file_processing_runs",
        ["id"],
        unique=False,
    )
    op.create_index(
        "ix_file_processing_runs_owner_user_id",
        "file_processing_runs",
        ["owner_user_id"],
        unique=False,
    )
    op.create_index(
        "ix_file_processing_runs_profile_id",
        "file_processing_runs",
        ["profile_id"],
        unique=False,
    )
    op.create_index(
        "ix_file_processing_runs_stage",
        "file_processing_runs",
        ["stage"],
        unique=False,
    )
    op.create_index(
        "ix_file_processing_runs_status",
        "file_processing_runs",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_file_processing_runs_workspace_id",
        "file_processing_runs",
        ["workspace_id"],
        unique=False,
    )

    with op.batch_alter_table("file_chunks") as batch_op:
        batch_op.alter_column("page_number", existing_type=sa.Integer(), nullable=True)
        batch_op.add_column(sa.Column("source_type", sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column("section_path", sa.String(length=500), nullable=True))
        batch_op.add_column(sa.Column("char_start", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("char_end", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("chunk_hash", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("parser_version", sa.String(length=50), nullable=True))
        batch_op.create_index("ix_file_chunks_chunk_hash", ["chunk_hash"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("file_chunks") as batch_op:
        batch_op.drop_index("ix_file_chunks_chunk_hash")
        batch_op.drop_column("parser_version")
        batch_op.drop_column("chunk_hash")
        batch_op.drop_column("char_end")
        batch_op.drop_column("char_start")
        batch_op.drop_column("section_path")
        batch_op.drop_column("source_type")
        batch_op.alter_column("page_number", existing_type=sa.Integer(), nullable=False)

    op.drop_index("ix_file_processing_runs_workspace_id", table_name="file_processing_runs")
    op.drop_index("ix_file_processing_runs_status", table_name="file_processing_runs")
    op.drop_index("ix_file_processing_runs_stage", table_name="file_processing_runs")
    op.drop_index("ix_file_processing_runs_profile_id", table_name="file_processing_runs")
    op.drop_index("ix_file_processing_runs_owner_user_id", table_name="file_processing_runs")
    op.drop_index("ix_file_processing_runs_id", table_name="file_processing_runs")
    op.drop_index("ix_file_processing_runs_file_id", table_name="file_processing_runs")
    op.drop_table("file_processing_runs")

    op.drop_index(
        "uq_file_relations_current_direction_type",
        table_name="file_relations",
    )
    op.drop_index(
        "ix_file_relations_workspace_status_confidence",
        table_name="file_relations",
    )
    op.drop_index("ix_file_relations_workspace_id", table_name="file_relations")
    op.drop_index("ix_file_relations_target_file_id", table_name="file_relations")
    op.drop_index("ix_file_relations_status", table_name="file_relations")
    op.drop_index("ix_file_relations_source_file_id", table_name="file_relations")
    op.drop_index("ix_file_relations_relation_type", table_name="file_relations")
    op.drop_index("ix_file_relations_owner_user_id", table_name="file_relations")
    op.drop_index("ix_file_relations_id", table_name="file_relations")
    op.drop_table("file_relations")

    op.drop_index("ix_file_profiles_workspace_id", table_name="file_profiles")
    op.drop_index("ix_file_profiles_status", table_name="file_profiles")
    op.drop_index("ix_file_profiles_owner_user_id", table_name="file_profiles")
    op.drop_index("ix_file_profiles_id", table_name="file_profiles")
    op.drop_index("ix_file_profiles_file_id", table_name="file_profiles")
    op.drop_table("file_profiles")
