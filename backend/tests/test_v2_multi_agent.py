import json
from pathlib import Path

import pytest

from app.agents.prompt_registry import PROMPTS
from app.agents.supervisor import SupervisorAgent
from app.agents.tool_registry import (
    QualityReviewInput,
    ToolContext,
    ToolExecutionError,
    validate_agent_tool,
)
from app.agents.v2_state import AgentStateV2, load_agent_state
from app.agents.v2_tools import run_quality_review
from app.models.task import Task
from app.models.task_plan import TaskPlan
from app.models.task_step import TaskStep
from app.services.llm_service import LLMResult
from app.services.task_queue_service import TaskQueueError, request_task_cancellation, retry_task
from app.services.v2_report_service import REQUIRED_REPORT_SECTIONS


def test_agent_state_version_and_sensitive_fields_are_rejected():
    valid = AgentStateV2(
        task_id=1,
        workspace_id=1,
        owner_user_id=1,
        user_request="分析",
        clarified_request="分析资料",
    )
    assert load_agent_state(valid.model_dump_json()).state_version == "2.04"
    with pytest.raises(Exception):
        load_agent_state(valid.model_dump_json().replace('"2.04"', '"2.03"', 1))
    with pytest.raises(Exception):
        AgentStateV2(
            task_id=1,
            workspace_id=1,
            owner_user_id=1,
            user_request="分析",
            clarified_request="分析",
            final_result={"file_path": "C:/private.csv"},
        )


def test_tool_registry_enforces_agent_permissions_and_prompt_coverage():
    validate_agent_tool("data_analysis_agent", "preset_multi_table_analysis")
    with pytest.raises(ToolExecutionError) as exc:
        validate_agent_tool("report_agent", "preset_multi_table_analysis")
    assert exc.value.code == "TOOL_PERMISSION_DENIED"
    assert {
        "clarification",
        "planning",
        "file_understanding_agent",
        "data_analysis_agent",
        "document_research_agent",
        "report_agent",
        "quality_review",
    }.issubset(PROMPTS)


def test_supervisor_invalid_model_json_falls_back(monkeypatch):
    monkeypatch.setattr("app.agents.supervisor.is_llm_ready", lambda: True)
    monkeypatch.setattr(
        "app.agents.supervisor.call_llm",
        lambda **kwargs: LLMResult(success=True, content='{"steps":"invalid"}'),
    )
    result = SupervisorAgent().generate_plan(
        user_request="请分析成绩并生成报告",
        workspace_context={
            "files": [{"file_id": 1, "file_type": "csv"}],
            "selected_file_ids": [1],
            "confirmed_relations": [],
            "unready_files": [],
        },
        use_deepseek=True,
    )
    assert result.fallback_used is True
    assert result.model_attempted is True
    assert result.plan.steps[-1].agent_type == "quality_review_agent"


def test_running_cancel_is_cooperative_and_retry_reuses_upstream(db_session):
    task = Task(
        user_input="分析",
        status="running",
        file_ids_json="[]",
        max_retries=1,
    )
    db_session.add(task)
    db_session.flush()
    request_task_cancellation(db_session, task)
    assert task.status == "running"
    assert task.cancellation_requested_at is not None

    task.status = "failed"
    task.cancellation_requested_at = None
    plan = TaskPlan(
        task_id=task.id,
        version=1,
        status="confirmed",
        goal="分析",
        assumptions_json="[]",
        steps_json="[]",
        selected_file_ids_json="[]",
        estimated_model_calls=0,
        estimated_tool_calls=3,
        created_by="test",
    )
    db_session.add(plan)
    db_session.flush()
    task.current_plan_id = plan.id
    upstream = TaskStep(
        task_id=task.id,
        plan_id=plan.id,
        step_key="upstream",
        step_order=1,
        agent_type="file_understanding_agent",
        tool_name="workspace_context_lookup",
        title="上游",
        status="completed",
        progress_percent=100,
        depends_on_json="[]",
        input_json="{}",
    )
    failed = TaskStep(
        task_id=task.id,
        plan_id=plan.id,
        step_key="failed",
        step_order=2,
        agent_type="report_agent",
        tool_name="structured_markdown_report",
        title="失败步骤",
        status="failed",
        progress_percent=0,
        depends_on_json='["upstream"]',
        input_json="{}",
    )
    downstream = TaskStep(
        task_id=task.id,
        plan_id=plan.id,
        step_key="review",
        step_order=3,
        agent_type="quality_review_agent",
        tool_name="deterministic_quality_review",
        title="审核",
        status="queued",
        progress_percent=0,
        depends_on_json='["failed"]',
        input_json="{}",
    )
    db_session.add_all([upstream, failed, downstream])
    db_session.commit()

    retry_task(db_session, task, step_id=failed.id)
    assert task.status == "queued"
    assert upstream.status == "completed"
    assert failed.status == "queued"
    assert downstream.status == "queued"
    task.status = "failed"
    db_session.commit()
    with pytest.raises(TaskQueueError) as exc:
        retry_task(db_session, task)
    assert exc.value.code == "TASK_RETRY_LIMIT_REACHED"


def test_deterministic_quality_review_checks_required_sections(
    db_session,
    tmp_path: Path,
):
    task = Task(
        user_input="生成报告",
        status="reviewing",
        file_ids_json="[]",
        owner_user_id=1,
        workspace_id=1,
    )
    db_session.add(task)
    db_session.flush()
    plan = TaskPlan(
        task_id=task.id,
        version=1,
        status="confirmed",
        goal="报告",
        assumptions_json="[]",
        steps_json="[]",
        selected_file_ids_json="[]",
        estimated_model_calls=0,
        estimated_tool_calls=2,
        created_by="test",
    )
    db_session.add(plan)
    db_session.flush()
    task.current_plan_id = plan.id
    report_step = TaskStep(
        task_id=task.id,
        plan_id=plan.id,
        step_key="write_report",
        step_order=1,
        agent_type="report_agent",
        tool_name="structured_markdown_report",
        title="报告",
        input_json="{}",
        status="completed",
        progress_percent=100,
        depends_on_json="[]",
    )
    review_step = TaskStep(
        task_id=task.id,
        plan_id=plan.id,
        step_key="review_quality",
        step_order=2,
        agent_type="quality_review_agent",
        tool_name="deterministic_quality_review",
        title="审核",
        input_json="{}",
        status="running",
        progress_percent=0,
        depends_on_json='["write_report"]',
    )
    db_session.add_all([report_step, review_step])
    report_file = tmp_path / "report.md"
    report_file.write_text(
        "# 报告\n\n" + "\n\n".join(f"## {section}\n内容" for section in REQUIRED_REPORT_SECTIONS),
        encoding="utf-8",
    )
    task.report_path = str(report_file)
    db_session.commit()
    state = AgentStateV2(
        task_id=task.id,
        workspace_id=task.workspace_id,
        owner_user_id=task.owner_user_id,
        user_request=task.user_input,
        clarified_request=task.user_input,
        report_sections=REQUIRED_REPORT_SECTIONS,
    )

    output = run_quality_review(
        ToolContext(db=db_session, task=task, step=review_step, state=state),
        QualityReviewInput(task_id=task.id),
    )
    assert output["status"] == "passed"
    report_file.write_text("# 缺少章节", encoding="utf-8")
    output = run_quality_review(
        ToolContext(db=db_session, task=task, step=review_step, state=state),
        QualityReviewInput(task_id=task.id),
    )
    assert output["status"] == "passed_with_warnings"
    assert any(item["code"] == "MISSING_REPORT_SECTION" for item in output["issues"])
