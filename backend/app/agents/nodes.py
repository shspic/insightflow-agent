import json
import time
from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from app.agents.classifier import classify_task as classify_user_task
from app.agents.executor import execute_selected_tools
from app.agents.planner import build_plan
from app.agents.router import select_tools
from app.agents.state import AgentState, AgentStateDict, state_from_dict, state_to_dict
from app.agents.writer import write_result as write_agent_result
from app.models.file import File
from app.models.task import Task
from app.models.tool_call import ToolCall

AgentStep = Callable[[AgentState], AgentState]
PayloadBuilder = Callable[[AgentState], dict[str, Any] | None]
ToolNameBuilder = Callable[[AgentState], str]


def build_node_map(db: Session) -> dict[str, Callable[[AgentStateDict], AgentStateDict]]:
    return {
        "classify_task": lambda state: _run_traced_node(
            db=db,
            raw_state=state,
            node_name="classify_task",
            tool_name="task_classifier",
            input_builder=lambda current: {"user_input": current.user_input},
            step=lambda current: _classify_task(current, db),
            output_builder=lambda current: {"task_type": current.task_type},
        ),
        "plan_task": lambda state: _run_traced_node(
            db=db,
            raw_state=state,
            node_name="plan_task",
            tool_name="planner",
            input_builder=lambda current: {"task_type": current.task_type},
            step=_plan_task,
            output_builder=lambda current: {"plan": current.plan},
        ),
        "route_tools": lambda state: _run_traced_node(
            db=db,
            raw_state=state,
            node_name="route_tools",
            tool_name="tool_router",
            input_builder=lambda current: {"task_type": current.task_type},
            step=_route_tools,
            output_builder=lambda current: {"selected_tools": current.selected_tools},
        ),
        "execute_tool": lambda state: _run_traced_node(
            db=db,
            raw_state=state,
            node_name="execute_tool",
            tool_name=_format_execute_tool_name,
            input_builder=lambda current: {"file_ids": current.file_ids, "selected_tools": current.selected_tools},
            step=lambda current: execute_selected_tools(current, db),
            output_builder=lambda current: {"tool_results": current.tool_results},
        ),
        "write_result": lambda state: _run_traced_node(
            db=db,
            raw_state=state,
            node_name="write_result",
            tool_name="result_writer",
            input_builder=lambda current: {"task_type": current.task_type, "errors": current.errors},
            step=write_agent_result,
            output_builder=lambda current: {"final_answer": current.final_answer},
        ),
        "save_result": lambda state: _run_traced_node(
            db=db,
            raw_state=state,
            node_name="save_result",
            tool_name="task_result_saver",
            input_builder=lambda current: {
                "task_id": current.task_id,
                "task_type": current.task_type,
                "has_errors": bool(current.errors),
            },
            step=lambda current: _save_result(current, db),
            output_builder=lambda current: {
                "task_id": current.task_id,
                "status": "failed" if current.errors else "success",
                "final_answer": current.final_answer,
            },
        ),
    }


def _classify_task(state: AgentState, db: Session) -> AgentState:
    state.task_type = classify_user_task(state.user_input, file_type=_get_primary_file_type(state, db))
    return state


def _plan_task(state: AgentState) -> AgentState:
    state.plan = build_plan(state.task_type)
    return state


def _route_tools(state: AgentState) -> AgentState:
    state.selected_tools = select_tools(state.task_type)
    return state


def _save_result(state: AgentState, db: Session) -> AgentState:
    task = db.get(Task, state.task_id)
    if task is None:
        raise ValueError("任务不存在，无法保存结果")

    task.task_type = state.task_type
    task.final_answer = state.final_answer
    task.status = "failed" if state.errors else "success"
    db.commit()
    db.refresh(task)
    return state


def _run_traced_node(
    db: Session,
    raw_state: AgentStateDict,
    node_name: str,
    tool_name: str | ToolNameBuilder,
    input_builder: PayloadBuilder,
    step: AgentStep,
    output_builder: PayloadBuilder,
) -> AgentStateDict:
    state = state_from_dict(raw_state)
    input_payload = input_builder(state)
    resolved_tool_name = tool_name(state) if callable(tool_name) else tool_name
    started_at = time.perf_counter()
    output_payload = None
    error_message = None
    status = "success"

    try:
        state = step(state)
        output_payload = output_builder(state)
    except Exception as exc:
        status = "failed"
        error_message = str(exc)
        state.errors.append(error_message)

    latency_ms = int((time.perf_counter() - started_at) * 1000)
    _record_tool_call(
        db=db,
        task_id=state.task_id,
        node_name=node_name,
        tool_name=resolved_tool_name,
        input_payload=input_payload,
        output_payload=output_payload,
        status=status,
        latency_ms=latency_ms,
        error_message=error_message,
    )
    return state_to_dict(state)


def _record_tool_call(
    db: Session,
    task_id: int,
    node_name: str,
    tool_name: str,
    input_payload: dict[str, Any] | None,
    output_payload: dict[str, Any] | None,
    status: str,
    latency_ms: int,
    error_message: str | None = None,
) -> None:
    tool_call = ToolCall(
        task_id=task_id,
        node_name=node_name,
        tool_name=tool_name,
        input_json=json.dumps(input_payload, ensure_ascii=False) if input_payload is not None else None,
        output_json=json.dumps(output_payload, ensure_ascii=False) if output_payload is not None else None,
        status=status,
        latency_ms=latency_ms,
        error_message=error_message,
    )
    db.add(tool_call)
    db.commit()


def _format_execute_tool_name(state: AgentState) -> str:
    if state.selected_tools:
        return ",".join(str(tool_name) for tool_name in state.selected_tools)

    if state.task_type == "unsupported":
        return "unsupported_handler"

    return "no_tool"


def _get_primary_file_type(state: AgentState, db: Session) -> str | None:
    if not state.file_ids:
        return None

    file_record = db.get(File, state.file_ids[0])
    if file_record is None:
        return None

    return file_record.file_type
