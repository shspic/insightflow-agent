"""阶段 6A 补修：Evidence 来源完整性字段 + ReviewRun.input_snapshot_json。

Revision ID: 20260812_0014
Revises: 20260810_0013
Create Date: 2026-08-12

语义（与既有字段不冲突）：
- evidences.content_hash 保持「证据记录规范哈希」语义不变，不改写历史数据；
- 新增独立来源完整性字段 provenance_type / source_file_hash /
  source_chunk_id / source_chunk_hash（全部可空，历史记录不动）；
- review_runs 新增 input_snapshot_json（与既有 input_snapshot_hash 配套）。

历史记录字段允许为空：不为已有行填充或改写任何值。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260812_0014"
down_revision: str | None = "20260810_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # SQLite 不支持对已有表 ALTER 添加 CHECK 约束，使用 batch 模式重建表；
    # 历史行全部可空，batch 重建保留既有数据。索引在 batch 之后单独创建，
    # 避免 batch 重建时对仍在变更中的列建索引。
    with op.batch_alter_table("evidences") as batch_op:
        batch_op.add_column(
            sa.Column("provenance_type", sa.String(length=20), nullable=True),
        )
        batch_op.add_column(
            sa.Column("source_file_hash", sa.String(length=64), nullable=True),
        )
        batch_op.add_column(
            sa.Column("source_chunk_id", sa.String(length=120), nullable=True),
        )
        batch_op.add_column(
            sa.Column("source_chunk_hash", sa.String(length=64), nullable=True),
        )
        batch_op.create_check_constraint(
            "ck_evidences_provenance_type",
            "provenance_type IS NULL OR provenance_type IN ('field_locator', 'corpus_chunk')",
        )
    op.create_index("ix_evidences_provenance_type", "evidences", ["provenance_type"])
    op.add_column(
        "review_runs",
        sa.Column("input_snapshot_json", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("review_runs", "input_snapshot_json")
    # 索引先于 batch 删除，避免 batch 重建表时复制引用已删列的索引
    op.drop_index("ix_evidences_provenance_type", table_name="evidences")
    with op.batch_alter_table("evidences") as batch_op:
        batch_op.drop_constraint("ck_evidences_provenance_type", type_="check")
        batch_op.drop_column("source_chunk_hash")
        batch_op.drop_column("source_chunk_id")
        batch_op.drop_column("source_file_hash")
        batch_op.drop_column("provenance_type")
