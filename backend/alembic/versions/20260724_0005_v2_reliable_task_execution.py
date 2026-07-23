"""新增 V2 可靠任务执行、计划、事件和 Agent 运行记录

Revision ID: 20260724_0005
Revises: 20260723_0004
Create Date: 2026-07-24

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260724_0005"
down_revision: Union[str, Sequence[str], None] = "20260723_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("tasks") as batch_op:
        batch_op.add_column(sa.Column("current_plan_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("current_step_id", sa.Integer(), nullable=True))
        batch_op.add_column(
            sa.Column("progress_percent", sa.Integer(), nullable=False, server_default="0")
        )
        batch_op.add_column(sa.Column("cancellation_requested_at", sa.DateTime(), nullable=True))
        batch_op.add_column(
            sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0")
        )
        batch_op.add_column(
            sa.Column("max_retries", sa.Integer(), nullable=False, server_default="1")
        )
        batch_op.add_column(sa.Column("queued_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("started_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("completed_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("failed_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("last_heartbeat_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("error_code", sa.String(length=80), nullable=True))
        batch_op.add_column(sa.Column("error_message", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("result_summary", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("report_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("context_version", sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column("agent_state_json", sa.Text(), nullable=True))
        batch_op.add_column(
            sa.Column("use_deepseek", sa.Integer(), nullable=False, server_default="0")
        )
        batch_op.add_column(sa.Column("report_preferences_json", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("worker_id", sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column("lease_expires_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("heartbeat_at", sa.DateTime(), nullable=True))
        batch_op.add_column(
            sa.Column("attempt_number", sa.Integer(), nullable=False, server_default="0")
        )
        batch_op.create_check_constraint(
            "ck_tasks_progress_percent",
            "progress_percent >= 0 AND progress_percent <= 100",
        )
        batch_op.create_index("ix_tasks_current_plan_id", ["current_plan_id"], unique=False)
        batch_op.create_index("ix_tasks_current_step_id", ["current_step_id"], unique=False)
        batch_op.create_index("ix_tasks_worker_id", ["worker_id"], unique=False)
        batch_op.create_index("ix_tasks_lease_expires_at", ["lease_expires_at"], unique=False)

    op.create_table(
        "task_clarifications",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("round_number", sa.Integer(), nullable=False),
        sa.Column("questions_json", sa.Text(), nullable=False),
        sa.Column("answers_json", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("answered_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'answered', 'skipped', 'expired')",
            name="ck_task_clarifications_status",
        ),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_task_clarifications_id", "task_clarifications", ["id"], unique=False)
    op.create_index(
        "ix_task_clarifications_task_id", "task_clarifications", ["task_id"], unique=False
    )
    op.create_index(
        "ix_task_clarifications_status", "task_clarifications", ["status"], unique=False
    )

    op.create_table(
        "task_plans",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("goal", sa.Text(), nullable=False),
        sa.Column("assumptions_json", sa.Text(), nullable=False),
        sa.Column("steps_json", sa.Text(), nullable=False),
        sa.Column("selected_file_ids_json", sa.Text(), nullable=False),
        sa.Column("estimated_model_calls", sa.Integer(), nullable=False),
        sa.Column("estimated_tool_calls", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(), nullable=True),
        sa.Column("superseded_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "status IN ('draft', 'confirmed', 'rejected', 'superseded')",
            name="ck_task_plans_status",
        ),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id", "version", name="uq_task_plans_task_version"),
    )
    op.create_index("ix_task_plans_id", "task_plans", ["id"], unique=False)
    op.create_index("ix_task_plans_task_id", "task_plans", ["task_id"], unique=False)
    op.create_index("ix_task_plans_status", "task_plans", ["status"], unique=False)

    op.create_table(
        "task_steps",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("plan_id", sa.Integer(), nullable=False),
        sa.Column("step_key", sa.String(length=80), nullable=False),
        sa.Column("step_order", sa.Integer(), nullable=False),
        sa.Column("agent_type", sa.String(length=80), nullable=False),
        sa.Column("tool_name", sa.String(length=120), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("input_json", sa.Text(), nullable=False),
        sa.Column("output_json", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("progress_percent", sa.Integer(), nullable=False),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("max_retries", sa.Integer(), nullable=False),
        sa.Column("depends_on_json", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("failed_at", sa.DateTime(), nullable=True),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'queued', 'running', 'completed', 'failed', "
            "'skipped', 'cancelled', 'retrying')",
            name="ck_task_steps_status",
        ),
        sa.CheckConstraint(
            "progress_percent >= 0 AND progress_percent <= 100",
            name="ck_task_steps_progress_percent",
        ),
        sa.ForeignKeyConstraint(["plan_id"], ["task_plans.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("plan_id", "step_key", name="uq_task_steps_plan_step_key"),
    )
    op.create_index("ix_task_steps_id", "task_steps", ["id"], unique=False)
    op.create_index("ix_task_steps_task_id", "task_steps", ["task_id"], unique=False)
    op.create_index("ix_task_steps_plan_id", "task_steps", ["plan_id"], unique=False)
    op.create_index("ix_task_steps_status", "task_steps", ["status"], unique=False)
    op.create_index("ix_task_steps_agent_type", "task_steps", ["agent_type"], unique=False)

    op.create_table(
        "task_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("event_version", sa.String(length=30), nullable=False),
        sa.Column("step_id", sa.Integer(), nullable=True),
        sa.Column("agent_type", sa.String(length=80), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=True),
        sa.Column("progress_percent", sa.Integer(), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "progress_percent IS NULL OR (progress_percent >= 0 AND progress_percent <= 100)",
            name="ck_task_events_progress_percent",
        ),
        sa.ForeignKeyConstraint(["step_id"], ["task_steps.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_task_events_id", "task_events", ["id"], unique=False)
    op.create_index("ix_task_events_task_id", "task_events", ["task_id"], unique=False)
    op.create_index("ix_task_events_event_type", "task_events", ["event_type"], unique=False)
    op.create_index("ix_task_events_step_id", "task_events", ["step_id"], unique=False)
    op.create_index("ix_task_events_task_id_id", "task_events", ["task_id", "id"], unique=False)

    op.create_table(
        "agent_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("step_id", sa.Integer(), nullable=True),
        sa.Column("agent_type", sa.String(length=80), nullable=False),
        sa.Column("run_number", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=80), nullable=True),
        sa.Column("model_name", sa.String(length=120), nullable=True),
        sa.Column("prompt_version", sa.String(length=50), nullable=True),
        sa.Column("input_summary_json", sa.Text(), nullable=True),
        sa.Column("output_summary_json", sa.Text(), nullable=True),
        sa.Column("tool_calls_json", sa.Text(), nullable=True),
        sa.Column("token_usage_json", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("fallback_used", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["step_id"], ["task_steps.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_runs_id", "agent_runs", ["id"], unique=False)
    op.create_index("ix_agent_runs_task_id", "agent_runs", ["task_id"], unique=False)
    op.create_index("ix_agent_runs_step_id", "agent_runs", ["step_id"], unique=False)
    op.create_index("ix_agent_runs_agent_type", "agent_runs", ["agent_type"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_agent_runs_agent_type", table_name="agent_runs")
    op.drop_index("ix_agent_runs_step_id", table_name="agent_runs")
    op.drop_index("ix_agent_runs_task_id", table_name="agent_runs")
    op.drop_index("ix_agent_runs_id", table_name="agent_runs")
    op.drop_table("agent_runs")

    op.drop_index("ix_task_events_task_id_id", table_name="task_events")
    op.drop_index("ix_task_events_step_id", table_name="task_events")
    op.drop_index("ix_task_events_event_type", table_name="task_events")
    op.drop_index("ix_task_events_task_id", table_name="task_events")
    op.drop_index("ix_task_events_id", table_name="task_events")
    op.drop_table("task_events")

    op.drop_index("ix_task_steps_agent_type", table_name="task_steps")
    op.drop_index("ix_task_steps_status", table_name="task_steps")
    op.drop_index("ix_task_steps_plan_id", table_name="task_steps")
    op.drop_index("ix_task_steps_task_id", table_name="task_steps")
    op.drop_index("ix_task_steps_id", table_name="task_steps")
    op.drop_table("task_steps")

    op.drop_index("ix_task_plans_status", table_name="task_plans")
    op.drop_index("ix_task_plans_task_id", table_name="task_plans")
    op.drop_index("ix_task_plans_id", table_name="task_plans")
    op.drop_table("task_plans")

    op.drop_index("ix_task_clarifications_status", table_name="task_clarifications")
    op.drop_index("ix_task_clarifications_task_id", table_name="task_clarifications")
    op.drop_index("ix_task_clarifications_id", table_name="task_clarifications")
    op.drop_table("task_clarifications")

    with op.batch_alter_table("tasks") as batch_op:
        batch_op.drop_index("ix_tasks_lease_expires_at")
        batch_op.drop_index("ix_tasks_worker_id")
        batch_op.drop_index("ix_tasks_current_step_id")
        batch_op.drop_index("ix_tasks_current_plan_id")
        batch_op.drop_constraint("ck_tasks_progress_percent", type_="check")
        batch_op.drop_column("attempt_number")
        batch_op.drop_column("heartbeat_at")
        batch_op.drop_column("lease_expires_at")
        batch_op.drop_column("worker_id")
        batch_op.drop_column("report_preferences_json")
        batch_op.drop_column("use_deepseek")
        batch_op.drop_column("agent_state_json")
        batch_op.drop_column("context_version")
        batch_op.drop_column("report_id")
        batch_op.drop_column("result_summary")
        batch_op.drop_column("error_message")
        batch_op.drop_column("error_code")
        batch_op.drop_column("last_heartbeat_at")
        batch_op.drop_column("failed_at")
        batch_op.drop_column("completed_at")
        batch_op.drop_column("started_at")
        batch_op.drop_column("queued_at")
        batch_op.drop_column("max_retries")
        batch_op.drop_column("retry_count")
        batch_op.drop_column("cancellation_requested_at")
        batch_op.drop_column("progress_percent")
        batch_op.drop_column("current_step_id")
        batch_op.drop_column("current_plan_id")
