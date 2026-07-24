"""新增 V2-05 报告、治理、评估、清理和运行监控结构

Revision ID: 20260724_0006
Revises: 20260724_0005
Create Date: 2026-07-24
"""

from datetime import datetime
import hashlib
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260724_0006"
down_revision: Union[str, Sequence[str], None] = "20260724_0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "prompt_versions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("prompt_name", sa.String(length=100), nullable=False),
        sa.Column("version", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("purpose", sa.String(length=500), nullable=False),
        sa.Column("template_text", sa.Text(), nullable=False),
        sa.Column("input_schema_json", sa.Text(), nullable=False),
        sa.Column("output_schema_json", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("activated_at", sa.DateTime(), nullable=True),
        sa.Column("retired_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint("status IN ('draft', 'active', 'retired')", name="ck_prompt_versions_status"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("prompt_name", "version", name="uq_prompt_versions_name_version"),
    )
    op.create_index("ix_prompt_versions_id", "prompt_versions", ["id"], unique=False)
    op.create_index("ix_prompt_versions_prompt_name", "prompt_versions", ["prompt_name"], unique=False)
    op.create_index("ix_prompt_versions_status", "prompt_versions", ["status"], unique=False)
    op.create_index("ix_prompt_versions_content_hash", "prompt_versions", ["content_hash"], unique=False)
    op.create_index(
        "uq_prompt_versions_one_active",
        "prompt_versions",
        ["prompt_name"],
        unique=True,
        sqlite_where=sa.text("status = 'active'"),
        postgresql_where=sa.text("status = 'active'"),
    )

    now = datetime.utcnow()
    prompt_table = sa.table(
        "prompt_versions",
        sa.column("prompt_name", sa.String),
        sa.column("version", sa.String),
        sa.column("status", sa.String),
        sa.column("purpose", sa.String),
        sa.column("template_text", sa.Text),
        sa.column("input_schema_json", sa.Text),
        sa.column("output_schema_json", sa.Text),
        sa.column("content_hash", sa.String),
        sa.column("created_at", sa.DateTime),
        sa.column("activated_at", sa.DateTime),
    )
    prompt_rows = []
    for name, purpose, input_schema, output_schema in [
        ("clarification", "判断必要追问", "ClarificationInput", "ClarificationOutput"),
        ("planning", "生成受限结构化计划", "PlanningInput", "TaskPlanDraft"),
        ("file_understanding_agent", "汇总文件 Profile 与上下文", "AgentStateV2", "FileUnderstandingOutput"),
        ("data_analysis_agent", "组织预设 Pandas 结果", "AgentStateV2", "DataAnalysisOutput"),
        ("document_research_agent", "组织文件检索证据", "AgentStateV2", "DocumentResearchOutput"),
        ("report_agent", "基于结构化结果生成受控报告", "AgentStateV2", "ReportOutput"),
        ("quality_review", "审核数字、引用、步骤和交付结构", "QualityReviewInput", "QualityReviewOutput"),
    ]:
        template = f"{purpose}。只使用已授权资源和注册工具；输出必须符合 {output_schema}。"
        prompt_rows.append(
            {
                "prompt_name": name,
                "version": "2.05.1",
                "status": "active",
                "purpose": purpose,
                "template_text": template,
                "input_schema_json": f'{{"schema":"{input_schema}"}}',
                "output_schema_json": f'{{"schema":"{output_schema}"}}',
                "content_hash": hashlib.sha256(template.encode("utf-8")).hexdigest(),
                "created_at": now,
                "activated_at": now,
            }
        )
    op.bulk_insert(prompt_table, prompt_rows)

    with op.batch_alter_table("agent_runs") as batch_op:
        batch_op.add_column(sa.Column("prompt_name", sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column("prompt_version_id", sa.Integer(), nullable=True))
        batch_op.create_index("ix_agent_runs_prompt_name", ["prompt_name"], unique=False)
        batch_op.create_index("ix_agent_runs_prompt_version_id", ["prompt_version_id"], unique=False)
        batch_op.create_foreign_key(
            "fk_agent_runs_prompt_version_id",
            "prompt_versions",
            ["prompt_version_id"],
            ["id"],
            ondelete="SET NULL",
        )

    with op.batch_alter_table("tool_calls") as batch_op:
        batch_op.add_column(sa.Column("step_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("agent_run_id", sa.Integer(), nullable=True))
        batch_op.create_index("ix_tool_calls_step_id", ["step_id"], unique=False)
        batch_op.create_index("ix_tool_calls_agent_run_id", ["agent_run_id"], unique=False)
        batch_op.create_foreign_key(
            "fk_tool_calls_step_id", "task_steps", ["step_id"], ["id"], ondelete="SET NULL"
        )
        batch_op.create_foreign_key(
            "fk_tool_calls_agent_run_id",
            "agent_runs",
            ["agent_run_id"],
            ["id"],
            ondelete="SET NULL",
        )

    op.create_table(
        "reports",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("workspace_id", sa.Integer(), nullable=False),
        sa.Column("owner_user_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("template_key", sa.String(length=80), nullable=False),
        sa.Column("language", sa.String(length=20), nullable=False),
        sa.Column("markdown_content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("generation_source", sa.String(length=40), nullable=False),
        sa.Column("quality_status", sa.String(length=50), nullable=True),
        sa.Column("quality_summary_json", sa.Text(), nullable=True),
        sa.Column("warnings_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("superseded_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "status IN ('generating', 'ready', 'ready_with_warnings', 'failed', 'superseded')",
            name="ck_reports_status",
        ),
        sa.CheckConstraint(
            "generation_source IN ('initial', 'user_regenerate', 'feedback_regenerate', 'retry')",
            name="ck_reports_generation_source",
        ),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id", "version", name="uq_reports_task_version"),
    )
    for name, columns in [
        ("ix_reports_id", ["id"]),
        ("ix_reports_task_id", ["task_id"]),
        ("ix_reports_workspace_id", ["workspace_id"]),
        ("ix_reports_owner_user_id", ["owner_user_id"]),
        ("ix_reports_status", ["status"]),
        ("ix_reports_template_key", ["template_key"]),
        ("ix_reports_content_hash", ["content_hash"]),
        ("ix_reports_quality_status", ["quality_status"]),
    ]:
        op.create_index(name, "reports", columns, unique=False)

    op.create_table(
        "report_assets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("report_id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("workspace_id", sa.Integer(), nullable=False),
        sa.Column("owner_user_id", sa.Integer(), nullable=False),
        sa.Column("asset_type", sa.String(length=40), nullable=False),
        sa.Column("format", sa.String(length=20), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("storage_key", sa.String(length=500), nullable=False),
        sa.Column("mime_type", sa.String(length=150), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("checksum", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("metadata_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "asset_type IN ('chart', 'table', 'source_attachment', 'markdown', "
            "'docx', 'pdf', 'image', 'citation_manifest')",
            name="ck_report_assets_type",
        ),
        sa.CheckConstraint(
            "status IN ('generating', 'ready', 'failed', 'superseded', 'deleted')",
            name="ck_report_assets_status",
        ),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["report_id"], ["reports.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("storage_key"),
    )
    for name, columns in [
        ("ix_report_assets_id", ["id"]),
        ("ix_report_assets_report_id", ["report_id"]),
        ("ix_report_assets_task_id", ["task_id"]),
        ("ix_report_assets_workspace_id", ["workspace_id"]),
        ("ix_report_assets_owner_user_id", ["owner_user_id"]),
        ("ix_report_assets_asset_type", ["asset_type"]),
        ("ix_report_assets_checksum", ["checksum"]),
        ("ix_report_assets_status", ["status"]),
        ("ix_report_assets_deleted_at", ["deleted_at"]),
    ]:
        op.create_index(name, "report_assets", columns, unique=False)

    op.create_table(
        "user_feedback",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("workspace_id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("report_id", sa.Integer(), nullable=True),
        sa.Column("feedback_type", sa.String(length=40), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("issue_category", sa.String(length=80), nullable=True),
        sa.Column("correction_json", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "feedback_type IN ('like', 'dislike', 'correction', 'regenerate_request', "
            "'missing_content', 'wrong_number', 'wrong_citation', 'other')",
            name="ck_user_feedback_type",
        ),
        sa.CheckConstraint("rating IS NULL OR (rating >= 1 AND rating <= 5)", name="ck_feedback_rating"),
        sa.ForeignKeyConstraint(["report_id"], ["reports.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    for name, columns in [
        ("ix_user_feedback_id", ["id"]),
        ("ix_user_feedback_user_id", ["user_id"]),
        ("ix_user_feedback_workspace_id", ["workspace_id"]),
        ("ix_user_feedback_task_id", ["task_id"]),
        ("ix_user_feedback_report_id", ["report_id"]),
        ("ix_user_feedback_feedback_type", ["feedback_type"]),
        ("ix_user_feedback_issue_category", ["issue_category"]),
        ("ix_user_feedback_status", ["status"]),
    ]:
        op.create_index(name, "user_feedback", columns, unique=False)

    _create_usage_tables()
    _create_evaluation_tables()
    _create_operations_tables()


def _create_usage_tables() -> None:
    op.create_table(
        "usage_counters",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("usage_date", sa.Date(), nullable=False),
        sa.Column("tasks_created", sa.Integer(), nullable=False),
        sa.Column("tasks_succeeded", sa.Integer(), nullable=False),
        sa.Column("tasks_failed", sa.Integer(), nullable=False),
        sa.Column("deepseek_calls", sa.Integer(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("tool_calls", sa.Integer(), nullable=False),
        sa.Column("file_storage_bytes", sa.Integer(), nullable=False),
        sa.Column("report_storage_bytes", sa.Integer(), nullable=False),
        sa.Column("task_duration_ms", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "usage_date", name="uq_usage_counters_user_date"),
    )
    op.create_index("ix_usage_counters_id", "usage_counters", ["id"], unique=False)
    op.create_index("ix_usage_counters_user_id", "usage_counters", ["user_id"], unique=False)
    op.create_index("ix_usage_counters_usage_date", "usage_counters", ["usage_date"], unique=False)

    op.create_table(
        "quota_overrides",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("quota_key", sa.String(length=80), nullable=False),
        sa.Column("limit_value", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("note", sa.String(length=500), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "quota_key", name="uq_quota_overrides_user_key"),
    )
    op.create_index("ix_quota_overrides_id", "quota_overrides", ["id"], unique=False)
    op.create_index("ix_quota_overrides_user_id", "quota_overrides", ["user_id"], unique=False)
    op.create_index("ix_quota_overrides_quota_key", "quota_overrides", ["quota_key"], unique=False)
    op.create_index("ix_quota_overrides_expires_at", "quota_overrides", ["expires_at"], unique=False)

    op.create_table(
        "model_usage_records",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=True),
        sa.Column("agent_run_id", sa.Integer(), nullable=True),
        sa.Column("provider", sa.String(length=80), nullable=False),
        sa.Column("model_name", sa.String(length=120), nullable=False),
        sa.Column("prompt_name", sa.String(length=100), nullable=True),
        sa.Column("prompt_version", sa.String(length=50), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("estimated_cost_micros", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["agent_run_id"], ["agent_runs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    for name, columns in [
        ("ix_model_usage_records_id", ["id"]),
        ("ix_model_usage_records_user_id", ["user_id"]),
        ("ix_model_usage_records_task_id", ["task_id"]),
        ("ix_model_usage_records_agent_run_id", ["agent_run_id"]),
        ("ix_model_usage_records_provider", ["provider"]),
        ("ix_model_usage_records_model_name", ["model_name"]),
        ("ix_model_usage_records_status", ["status"]),
    ]:
        op.create_index(name, "model_usage_records", columns, unique=False)


def _create_evaluation_tables() -> None:
    op.create_table(
        "evaluation_datasets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("version", sa.String(length=50), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", "version", name="uq_evaluation_datasets_name_version"),
    )
    op.create_index("ix_evaluation_datasets_id", "evaluation_datasets", ["id"], unique=False)
    op.create_index("ix_evaluation_datasets_name", "evaluation_datasets", ["name"], unique=False)

    op.create_table(
        "evaluation_cases",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("dataset_id", sa.Integer(), nullable=False),
        sa.Column("case_key", sa.String(length=120), nullable=False),
        sa.Column("category", sa.String(length=80), nullable=False),
        sa.Column("input_task", sa.Text(), nullable=False),
        sa.Column("resource_refs_json", sa.Text(), nullable=False),
        sa.Column("expected_agent_json", sa.Text(), nullable=False),
        sa.Column("expected_tools_json", sa.Text(), nullable=False),
        sa.Column("expected_citations_json", sa.Text(), nullable=False),
        sa.Column("expected_refusal", sa.Integer(), nullable=False),
        sa.Column("auto_checks_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["dataset_id"], ["evaluation_datasets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dataset_id", "case_key", name="uq_evaluation_cases_dataset_key"),
    )
    op.create_index("ix_evaluation_cases_id", "evaluation_cases", ["id"], unique=False)
    op.create_index("ix_evaluation_cases_dataset_id", "evaluation_cases", ["dataset_id"], unique=False)
    op.create_index("ix_evaluation_cases_category", "evaluation_cases", ["category"], unique=False)

    op.create_table(
        "evaluation_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("dataset_id", sa.Integer(), nullable=False),
        sa.Column("mode", sa.String(length=30), nullable=False),
        sa.Column("category_filter", sa.String(length=80), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("prompt_versions_json", sa.Text(), nullable=False),
        sa.Column("model_version", sa.String(length=120), nullable=True),
        sa.Column("metrics_json", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["dataset_id"], ["evaluation_datasets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_evaluation_runs_id", "evaluation_runs", ["id"], unique=False)
    op.create_index("ix_evaluation_runs_dataset_id", "evaluation_runs", ["dataset_id"], unique=False)
    op.create_index("ix_evaluation_runs_mode", "evaluation_runs", ["mode"], unique=False)
    op.create_index("ix_evaluation_runs_status", "evaluation_runs", ["status"], unique=False)

    op.create_table(
        "evaluation_results",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("case_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("actual_result_json", sa.Text(), nullable=False),
        sa.Column("metrics_json", sa.Text(), nullable=False),
        sa.Column("errors_json", sa.Text(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("model_calls", sa.Integer(), nullable=False),
        sa.Column("tool_calls", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["case_id"], ["evaluation_cases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["evaluation_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "case_id", name="uq_evaluation_results_run_case"),
    )
    op.create_index("ix_evaluation_results_id", "evaluation_results", ["id"], unique=False)
    op.create_index("ix_evaluation_results_run_id", "evaluation_results", ["run_id"], unique=False)
    op.create_index("ix_evaluation_results_case_id", "evaluation_results", ["case_id"], unique=False)
    op.create_index("ix_evaluation_results_status", "evaluation_results", ["status"], unique=False)


def _create_operations_tables() -> None:
    op.create_table(
        "cleanup_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("cleanup_type", sa.String(length=80), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("scanned_count", sa.Integer(), nullable=False),
        sa.Column("deleted_count", sa.Integer(), nullable=False),
        sa.Column("released_bytes", sa.Integer(), nullable=False),
        sa.Column("error_count", sa.Integer(), nullable=False),
        sa.Column("dry_run", sa.Integer(), nullable=False),
        sa.Column("execution_source", sa.String(length=50), nullable=False),
        sa.Column("details_json", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_cleanup_runs_id", "cleanup_runs", ["id"], unique=False)
    op.create_index("ix_cleanup_runs_cleanup_type", "cleanup_runs", ["cleanup_type"], unique=False)

    op.create_table(
        "worker_statuses",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("worker_id", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("last_heartbeat_at", sa.DateTime(), nullable=False),
        sa.Column("current_task_id", sa.Integer(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("completed_tasks", sa.Integer(), nullable=False),
        sa.Column("failed_tasks", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_worker_statuses_id", "worker_statuses", ["id"], unique=False)
    op.create_index("ix_worker_statuses_worker_id", "worker_statuses", ["worker_id"], unique=True)
    op.create_index("ix_worker_statuses_status", "worker_statuses", ["status"], unique=False)
    op.create_index(
        "ix_worker_statuses_last_heartbeat_at", "worker_statuses", ["last_heartbeat_at"], unique=False
    )
    op.create_index(
        "ix_worker_statuses_current_task_id", "worker_statuses", ["current_task_id"], unique=False
    )


def downgrade() -> None:
    for table in [
        "worker_statuses",
        "cleanup_runs",
        "evaluation_results",
        "evaluation_runs",
        "evaluation_cases",
        "evaluation_datasets",
        "model_usage_records",
        "quota_overrides",
        "usage_counters",
        "user_feedback",
        "report_assets",
        "reports",
    ]:
        op.drop_table(table)

    with op.batch_alter_table("tool_calls") as batch_op:
        batch_op.drop_constraint("fk_tool_calls_agent_run_id", type_="foreignkey")
        batch_op.drop_constraint("fk_tool_calls_step_id", type_="foreignkey")
        batch_op.drop_index("ix_tool_calls_agent_run_id")
        batch_op.drop_index("ix_tool_calls_step_id")
        batch_op.drop_column("agent_run_id")
        batch_op.drop_column("step_id")

    with op.batch_alter_table("agent_runs") as batch_op:
        batch_op.drop_constraint("fk_agent_runs_prompt_version_id", type_="foreignkey")
        batch_op.drop_index("ix_agent_runs_prompt_version_id")
        batch_op.drop_index("ix_agent_runs_prompt_name")
        batch_op.drop_column("prompt_version_id")
        batch_op.drop_column("prompt_name")

    op.drop_index("uq_prompt_versions_one_active", table_name="prompt_versions")
    op.drop_table("prompt_versions")
