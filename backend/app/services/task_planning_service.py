import json
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agents.supervisor import SupervisorAgent, validate_plan_steps
from app.agents.v2_state import AgentStateV2, load_agent_state
from app.core.config import settings
from app.models.agent_run import AgentRun
from app.models.task import Task
from app.models.task_clarification import TaskClarification
from app.models.task_event import TaskEvent
from app.models.task_plan import TaskPlan
from app.models.task_step import TaskStep
from app.models.user import User
from app.models.usage import ModelUsageRecord
from app.schemas.task_execution import (
    PlanPatchRequest,
    PlanStepInput,
    TaskDraftCreate,
)
from app.services.llm_service import is_llm_ready
from app.services.quota_service import (
    QuotaExceeded,
    check_plan_confirmation,
    check_model_call,
    check_task_creation,
    increment_usage,
)
from app.services.prompt_version_service import get_active_prompt
from app.services.task_event_service import append_task_event, task_event_response
from app.services.task_state_machine import transition_task
from app.services.workspace_context_service import (
    WorkspaceContextError,
    build_workspace_context,
)
from app.services.workspace_service import safe_public_text


class TaskPlanningError(Exception):
    def __init__(self, message: str, code: str = "TASK_PLANNING_ERROR") -> None:
        self.message = message
        self.code = code
        super().__init__(message)


def create_task_draft(
    db: Session,
    *,
    workspace_id: int,
    owner_user_id: int,
    payload: TaskDraftCreate,
) -> Task:
    owner = db.get(User, owner_user_id)
    if owner is None:
        raise TaskPlanningError("任务所有者不存在", "USER_NOT_FOUND")
    try:
        check_task_creation(db, owner)
    except QuotaExceeded as exc:
        raise TaskPlanningError(str(exc), "QUOTA_EXCEEDED") from exc
    context = _context(db, workspace_id, owner_user_id, payload.selected_file_ids)
    task = Task(
        owner_user_id=owner_user_id,
        workspace_id=workspace_id,
        user_input=payload.user_request.strip(),
        task_type="multi_modal_analysis",
        status="draft",
        file_ids_json=_json(payload.selected_file_ids),
        progress_percent=0,
        max_retries=max(0, settings.task_max_retries),
        context_version=context.context_version,
        use_deepseek=int(payload.use_deepseek),
        report_preferences_json=_json(payload.report_preferences or {}),
    )
    db.add(task)
    db.flush()
    increment_usage(db, owner_user_id, tasks_created=1)
    append_task_event(
        db,
        task_id=task.id,
        event_type="task_draft_created",
        message="任务草稿已创建，尚未执行分析工具。",
        status=task.status,
        progress_percent=0,
        payload={"selected_file_ids": payload.selected_file_ids},
    )
    questions = _clarification_questions(payload.user_request, context.model_dump())
    if questions:
        _create_clarification(db, task, questions)
        transition_task(
            db,
            task,
            "awaiting_clarification",
            message="需要补充信息后才能生成可靠计划。",
            progress_percent=2,
        )
    else:
        _generate_plan(db, task, context.model_dump(), clarified_request=task.user_input)
    db.commit()
    db.refresh(task)
    return task


def answer_clarification(
    db: Session,
    *,
    task: Task,
    answers: dict[str, Any],
    continue_with_recommendation: bool,
) -> Task:
    if task.status != "awaiting_clarification":
        raise TaskPlanningError("当前任务不在等待追问状态", "INVALID_TASK_STATUS")
    clarification = db.scalar(
        select(TaskClarification)
        .where(
            TaskClarification.task_id == task.id,
            TaskClarification.status == "pending",
        )
        .order_by(TaskClarification.round_number.desc())
    )
    if clarification is None:
        raise TaskPlanningError("没有待回答的追问", "CLARIFICATION_NOT_FOUND")
    selected_ids = _selected_file_ids(task)
    answer_file_ids = answers.get("selected_file_ids")
    if isinstance(answer_file_ids, list):
        selected_ids = list(dict.fromkeys(int(item) for item in answer_file_ids))
        task.file_ids_json = _json(selected_ids)
    clarification.answers_json = _json(
        {
            "answers": answers,
            "continue_with_recommendation": continue_with_recommendation,
        }
    )
    clarification.status = "skipped" if continue_with_recommendation else "answered"
    clarification.answered_at = datetime.utcnow()
    append_task_event(
        db,
        task_id=task.id,
        event_type="clarification_answered",
        message=(
            "用户选择按系统推荐继续。"
            if continue_with_recommendation
            else "用户已回答追问。"
        ),
        status=task.status,
        progress_percent=task.progress_percent,
        payload={"round_number": clarification.round_number},
    )
    context = _context(db, task.workspace_id, task.owner_user_id, selected_ids)
    remaining = _clarification_questions(task.user_input, context.model_dump())
    if (
        remaining
        and clarification.round_number < max(1, settings.task_max_clarification_rounds)
        and not continue_with_recommendation
    ):
        _create_clarification(db, task, remaining)
        db.commit()
        return task
    if not selected_ids:
        raise TaskPlanningError(
            "未选择必要文件，达到追问上限后仍无法安全生成执行计划",
            "NO_SELECTED_FILES",
        )
    clarified_request = task.user_input
    if answers:
        clarified_request += "\n澄清信息：" + _json(answers)[:2000]
    _generate_plan(db, task, context.model_dump(), clarified_request=clarified_request)
    db.commit()
    db.refresh(task)
    return task


def regenerate_plan(db: Session, *, task: Task) -> TaskPlan:
    if task.status != "awaiting_confirmation":
        raise TaskPlanningError("只有等待确认的任务可以重新生成计划", "INVALID_TASK_STATUS")
    supervisor_plan_count = db.scalar(
        select(func.count(TaskPlan.id)).where(
            TaskPlan.task_id == task.id,
            TaskPlan.created_by.in_(["supervisor", "supervisor_fallback"]),
        )
    ) or 0
    if supervisor_plan_count - 1 >= max(0, settings.agent_max_replan_count):
        raise TaskPlanningError("已达到 Supervisor 最大重新规划次数", "REPLAN_LIMIT_REACHED")
    transition_task(db, task, "planning", message="正在重新生成计划。")
    context = _context(
        db,
        task.workspace_id,
        task.owner_user_id,
        _selected_file_ids(task),
    )
    state = _load_or_create_state(task, context.model_dump(), task.user_input)
    plan = _generate_plan(
        db,
        task,
        context.model_dump(),
        clarified_request=state.clarified_request,
    )
    db.commit()
    return plan


def patch_plan(
    db: Session,
    *,
    task: Task,
    plan: TaskPlan,
    payload: PlanPatchRequest,
) -> TaskPlan:
    if task.status != "awaiting_confirmation" or plan.status != "draft":
        raise TaskPlanningError("当前计划不能修改", "INVALID_PLAN_STATUS")
    selected_ids = (
        list(dict.fromkeys(payload.selected_file_ids))
        if payload.selected_file_ids is not None
        else _json_list(plan.selected_file_ids_json)
    )
    context = _context(db, task.workspace_id, task.owner_user_id, selected_ids)
    steps = (
        payload.steps
        if payload.steps is not None
        else [PlanStepInput.model_validate(item) for item in _json_object_list(plan.steps_json)]
    )
    validate_plan_steps(steps)
    plan.status = "superseded"
    plan.superseded_at = datetime.utcnow()
    new_plan = TaskPlan(
        task_id=task.id,
        version=_next_plan_version(db, task.id),
        status="draft",
        goal=payload.goal or plan.goal,
        assumptions_json=_json(
            payload.assumptions
            if payload.assumptions is not None
            else _json_list(plan.assumptions_json)
        ),
        steps_json=_json([item.model_dump() for item in steps]),
        selected_file_ids_json=_json(selected_ids),
        estimated_model_calls=plan.estimated_model_calls,
        estimated_tool_calls=len(steps),
        created_by="user_modified",
    )
    db.add(new_plan)
    db.flush()
    task.current_plan_id = new_plan.id
    task.file_ids_json = _json(selected_ids)
    task.context_version = context.context_version
    state = _load_or_create_state(task, context.model_dump(), task.user_input)
    state.selected_file_ids = selected_ids
    state.workspace_context = context.model_dump()
    state.confirmed_relations = context.confirmed_relations
    state.assumptions = _json_list(new_plan.assumptions_json)
    state.current_plan = plan_response(new_plan)
    task.agent_state_json = state.model_dump_json()
    append_task_event(
        db,
        task_id=task.id,
        event_type="plan_version_created",
        message=f"计划已修改并生成版本 {new_plan.version}。",
        status=task.status,
        progress_percent=task.progress_percent,
        payload={"plan_id": new_plan.id, "version": new_plan.version},
    )
    db.commit()
    db.refresh(new_plan)
    return new_plan


def confirm_plan(db: Session, *, task: Task, plan: TaskPlan) -> Task:
    owner = db.get(User, task.owner_user_id)
    if owner is None:
        raise TaskPlanningError("任务所有者不存在", "USER_NOT_FOUND")
    try:
        check_plan_confirmation(db, owner, task)
    except QuotaExceeded as exc:
        raise TaskPlanningError(str(exc), "QUOTA_EXCEEDED") from exc
    if task.status != "awaiting_confirmation":
        raise TaskPlanningError("当前任务不等待计划确认", "INVALID_TASK_STATUS")
    if plan.id != task.current_plan_id or plan.status != "draft":
        raise TaskPlanningError("只能确认当前草稿计划", "INVALID_PLAN_STATUS")
    selected_ids = _json_list(plan.selected_file_ids_json)
    _context(db, task.workspace_id, task.owner_user_id, selected_ids)
    step_models = [
        PlanStepInput.model_validate(item) for item in _json_object_list(plan.steps_json)
    ]
    validate_plan_steps(step_models)
    plan.status = "confirmed"
    plan.confirmed_at = datetime.utcnow()
    for order, item in enumerate(step_models, start=1):
        db.add(
            TaskStep(
                task_id=task.id,
                plan_id=plan.id,
                step_key=item.step_key,
                step_order=order,
                agent_type=item.agent_type,
                tool_name=item.tool_name,
                title=item.title,
                description=item.description,
                input_json=_json({"parameters": item.parameters, "optional": item.optional}),
                status="queued",
                progress_percent=0,
                retry_count=0,
                max_retries=max(0, settings.task_max_retries),
                depends_on_json=_json(item.depends_on),
            )
        )
    transition_task(
        db,
        task,
        "queued",
        message="计划已确认，任务已进入持久化队列。",
        progress_percent=5,
        event_type="plan_confirmed",
        payload={"plan_id": plan.id, "version": plan.version},
    )
    db.commit()
    db.refresh(task)
    return task


def task_execution_detail(db: Session, task: Task) -> dict[str, Any]:
    plan = db.get(TaskPlan, task.current_plan_id) if task.current_plan_id else None
    clarifications = list(
        db.scalars(
            select(TaskClarification)
            .where(TaskClarification.task_id == task.id)
            .order_by(TaskClarification.round_number.asc())
        ).all()
    )
    steps = list(
        db.scalars(
            select(TaskStep)
            .where(TaskStep.task_id == task.id)
            .order_by(TaskStep.step_order.asc())
        ).all()
    )
    events = list(
        db.scalars(
            select(TaskEvent)
            .where(TaskEvent.task_id == task.id)
            .order_by(TaskEvent.id.desc())
            .limit(30)
        ).all()
    )
    state = None
    if task.agent_state_json:
        try:
            state = load_agent_state(task.agent_state_json)
        except Exception:
            state = None
    result_summary = _json_dict(task.result_summary)
    return {
        "id": task.id,
        "workspace_id": task.workspace_id,
        "user_request": task.user_input,
        "task_type": task.task_type,
        "status": task.status,
        "selected_file_ids": _selected_file_ids(task),
        "current_plan": plan_response(plan) if plan else None,
        "clarifications": [clarification_response(item) for item in clarifications],
        "steps": [step_response(item) for item in steps],
        "progress_percent": task.progress_percent,
        "current_step_id": task.current_step_id,
        "cancellation_requested_at": task.cancellation_requested_at,
        "retry_count": task.retry_count,
        "max_retries": task.max_retries,
        "result_summary": result_summary or None,
        "final_result": state.final_result if state else None,
        "report_id": task.report_id,
        "has_report": bool(task.report_path),
        "latest_events": [task_event_response(item) for item in reversed(events)],
        "model_available": is_llm_ready(),
        "created_at": task.created_at,
        "updated_at": task.updated_at,
    }


def plan_response(plan: TaskPlan) -> dict[str, Any]:
    return {
        "id": plan.id,
        "task_id": plan.task_id,
        "version": plan.version,
        "status": plan.status,
        "goal": plan.goal,
        "assumptions": _json_list(plan.assumptions_json),
        "steps": _json_object_list(plan.steps_json),
        "selected_file_ids": _json_list(plan.selected_file_ids_json),
        "estimated_model_calls": plan.estimated_model_calls,
        "estimated_tool_calls": plan.estimated_tool_calls,
        "created_by": plan.created_by,
        "created_at": plan.created_at,
        "confirmed_at": plan.confirmed_at,
    }


def step_response(step: TaskStep) -> dict[str, Any]:
    return {
        "id": step.id,
        "step_key": step.step_key,
        "step_order": step.step_order,
        "agent_type": step.agent_type,
        "tool_name": step.tool_name,
        "title": step.title,
        "description": step.description,
        "status": step.status,
        "progress_percent": step.progress_percent,
        "retry_count": step.retry_count,
        "max_retries": step.max_retries,
        "depends_on": _json_list(step.depends_on_json),
        "output": _json_dict(step.output_json) or None,
        "error_code": step.error_code,
        "error_message": safe_public_text(step.error_message),
    }


def clarification_response(item: TaskClarification) -> dict[str, Any]:
    answers = _json_dict(item.answers_json)
    return {
        "id": item.id,
        "round_number": item.round_number,
        "questions": _json_object_list(item.questions_json),
        "answers": answers or None,
        "status": item.status,
        "created_at": item.created_at,
        "answered_at": item.answered_at,
    }


def _generate_plan(
    db: Session,
    task: Task,
    context: dict[str, Any],
    *,
    clarified_request: str,
) -> TaskPlan:
    if task.status in {"draft", "awaiting_clarification"}:
        transition_task(db, task, "planning", message="Supervisor 正在生成计划草稿。", progress_percent=3)
    current = db.get(TaskPlan, task.current_plan_id) if task.current_plan_id else None
    if current is not None and current.status == "draft":
        current.status = "superseded"
        current.superseded_at = datetime.utcnow()
    owner = db.get(User, task.owner_user_id)
    if owner is None:
        raise TaskPlanningError("任务所有者不存在", "USER_NOT_FOUND")
    if task.use_deepseek and is_llm_ready():
        try:
            check_model_call(db, owner, task)
        except QuotaExceeded as exc:
            raise TaskPlanningError(str(exc), "QUOTA_EXCEEDED") from exc
    result = SupervisorAgent().generate_plan(
        user_request=clarified_request,
        workspace_context=context,
        use_deepseek=bool(task.use_deepseek),
    )
    plan = TaskPlan(
        task_id=task.id,
        version=_next_plan_version(db, task.id),
        status="draft",
        goal=result.plan.goal,
        assumptions_json=_json(result.plan.assumptions),
        steps_json=_json([item.model_dump() for item in result.plan.steps]),
        selected_file_ids_json=_json(context.get("selected_file_ids") or []),
        estimated_model_calls=result.plan.estimated_model_calls,
        estimated_tool_calls=result.plan.estimated_tool_calls,
        created_by="supervisor_fallback" if result.fallback_used else "supervisor",
    )
    db.add(plan)
    db.flush()
    task.current_plan_id = plan.id
    task.file_ids_json = plan.selected_file_ids_json
    state = AgentStateV2(
        task_id=task.id,
        workspace_id=task.workspace_id,
        owner_user_id=task.owner_user_id,
        user_request=task.user_input,
        clarified_request=clarified_request,
        assumptions=result.plan.assumptions,
        selected_file_ids=_json_list(plan.selected_file_ids_json),
        workspace_context=context,
        confirmed_relations=context.get("confirmed_relations") or [],
        current_plan=plan_response(plan),
        model_budget=max(
            0,
            settings.task_model_call_budget - int(result.model_attempted),
        ),
        tool_budget=max(0, settings.task_tool_call_budget),
    )
    task.agent_state_json = state.model_dump_json()
    prompt_record = get_active_prompt(db, "planning")
    agent_run = AgentRun(
            task_id=task.id,
            step_id=None,
            agent_type="supervisor",
            run_number=plan.version,
            provider=settings.llm_provider if result.model_attempted else "deterministic",
            model_name=settings.llm_model if result.model_attempted else None,
            prompt_name=prompt_record.prompt_name,
            prompt_version=prompt_record.version,
            prompt_version_id=prompt_record.id,
            input_summary_json=_json(
                {
                    "selected_file_count": len(state.selected_file_ids),
                    "context_version": task.context_version,
                }
            ),
            output_summary_json=_json(
                {
                    "plan_id": plan.id,
                    "step_count": len(result.plan.steps),
                    "message": result.model_message,
                }
            ),
            tool_calls_json="[]",
            token_usage_json=_json(result.token_usage) if result.token_usage else None,
            duration_ms=result.duration_ms,
            status="completed",
            fallback_used=int(result.fallback_used),
            completed_at=datetime.utcnow(),
        )
    db.add(agent_run)
    db.flush()
    if result.model_attempted:
        token_usage = result.token_usage or {}
        input_tokens = int(token_usage.get("prompt_tokens") or token_usage.get("input_tokens") or 0)
        output_tokens = int(
            token_usage.get("completion_tokens") or token_usage.get("output_tokens") or 0
        )
        db.add(
            ModelUsageRecord(
                user_id=owner.id,
                task_id=task.id,
                agent_run_id=agent_run.id,
                provider=settings.llm_provider,
                model_name=settings.llm_model,
                prompt_name=prompt_record.prompt_name,
                prompt_version=prompt_record.version,
                status="failed" if result.fallback_used else "success",
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                duration_ms=int(result.duration_ms or 0),
                error_code="MODEL_FALLBACK" if result.fallback_used else None,
                metadata_json=_json({"fallback_used": result.fallback_used}),
            )
        )
        increment_usage(
            db,
            owner.id,
            deepseek_calls=1,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
    transition_task(
        db,
        task,
        "awaiting_confirmation",
        message="计划草稿已生成，等待用户确认。",
        progress_percent=5,
        event_type="plan_draft_created",
        payload={
            "plan_id": plan.id,
            "version": plan.version,
            "fallback_used": result.fallback_used,
            "model_message": result.model_message,
        },
    )
    return plan


def _create_clarification(
    db: Session,
    task: Task,
    questions: list[dict[str, Any]],
) -> TaskClarification:
    round_number = (
        db.scalar(
            select(func.max(TaskClarification.round_number)).where(
                TaskClarification.task_id == task.id
            )
        )
        or 0
    ) + 1
    clarification = TaskClarification(
        task_id=task.id,
        round_number=round_number,
        questions_json=_json(questions[:3]),
        status="pending",
    )
    db.add(clarification)
    db.flush()
    append_task_event(
        db,
        task_id=task.id,
        event_type="clarification_requested",
        message=f"Agent 发起第 {round_number} 轮追问。",
        status=task.status,
        progress_percent=task.progress_percent,
        payload={"round_number": round_number, "question_count": len(questions[:3])},
    )
    return clarification


def _clarification_questions(
    user_request: str,
    context: dict[str, Any],
) -> list[dict[str, Any]]:
    questions = []
    if len(user_request.strip()) < 6 or user_request.strip() in {"分析", "看看", "总结"}:
        questions.append(
            {
                "id": "goal",
                "question": "你希望重点回答什么问题或支持什么决策？",
                "reason": "当前目标过于宽泛，无法安全选择分析步骤。",
                "recommended_answer": "先做数据质量、主要趋势、风险和行动建议的综合分析。",
            }
        )
    if not context.get("selected_file_ids"):
        questions.append(
            {
                "id": "selected_file_ids",
                "question": "请选择本次任务要使用的文件。",
                "reason": "没有文件时无法执行文件分析。",
                "recommended_answer": "选择与目标最直接相关且 Profile 已 ready 的文件。",
            }
        )
    relation_words = {"合并", "连接", "匹配", "关联", "join", "merge"}
    if (
        len(context.get("selected_file_ids") or []) > 1
        and any(word in user_request.lower() for word in relation_words)
        and not context.get("confirmed_relations")
    ):
        questions.append(
            {
                "id": "file_relation",
                "question": "多个文件应通过哪个字段或关系进行关联？",
                "reason": "未确认连接字段时不能自动拼接表格或跨文件记录。",
                "recommended_answer": "先按文件分别分析并列展示，不执行行级合并。",
            }
        )
    return questions[:3]


def _context(
    db: Session,
    workspace_id: int,
    owner_user_id: int,
    selected_file_ids: list[int],
):
    try:
        return build_workspace_context(
            db,
            workspace_id=workspace_id,
            owner_user_id=owner_user_id,
            selected_file_ids=selected_file_ids,
        )
    except WorkspaceContextError as exc:
        raise TaskPlanningError(exc.message, exc.code) from exc


def _load_or_create_state(
    task: Task,
    context: dict[str, Any],
    clarified_request: str,
) -> AgentStateV2:
    if task.agent_state_json:
        return load_agent_state(task.agent_state_json)
    return AgentStateV2(
        task_id=task.id,
        workspace_id=task.workspace_id,
        owner_user_id=task.owner_user_id,
        user_request=task.user_input,
        clarified_request=clarified_request,
        selected_file_ids=_selected_file_ids(task),
        workspace_context=context,
        confirmed_relations=context.get("confirmed_relations") or [],
    )


def _next_plan_version(db: Session, task_id: int) -> int:
    return (
        db.scalar(select(func.max(TaskPlan.version)).where(TaskPlan.task_id == task_id))
        or 0
    ) + 1


def _selected_file_ids(task: Task) -> list[int]:
    return _json_list(task.file_ids_json)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _json_list(value: str | None) -> list[Any]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def _json_dict(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _json_object_list(value: str | None) -> list[dict[str, Any]]:
    return [item for item in _json_list(value) if isinstance(item, dict)]
