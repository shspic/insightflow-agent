import json
import time
from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from app.agents.classifier import classify_task
from app.agents.executor import execute_selected_tools
from app.agents.planner import build_plan
from app.agents.router import select_tools
from app.agents.state import AgentState
from app.agents.writer import write_result
from app.models.tool_call import ToolCall

AgentStep = Callable[[AgentState], AgentState]


def run_basic_agent(task_id: int, user_input: str, file_ids: list[int], db: Session) -> AgentState:
    state = AgentState(task_id=task_id, user_input=user_input, file_ids=file_ids)

    state = _run_step(
        db=db,
        state=state,
        node_name="classify_task",
        tool_name="rule_classifier",
        input_payload={"user_input": user_input},
        step=lambda current: _classify(current),
        output_builder=lambda current: {"task_type": current.task_type},
    )
    state = _run_step(
        db=db,
        state=state,
        node_name="plan_task",
        tool_name="rule_planner",
        input_payload={"task_type": state.task_type},
        step=lambda current: _plan(current),
        output_builder=lambda current: {"plan": current.plan},
    )
    state = _run_step(
        db=db,
        state=state,
        node_name="route_tools",
        tool_name="rule_router",
        input_payload={"task_type": state.task_type},
        step=lambda current: _route(current),
        output_builder=lambda current: {"selected_tools": current.selected_tools},
    )
    state = _run_step(
        db=db,
        state=state,
        node_name="execute_tool",
        tool_name=_format_tool_name(state.selected_tools),
        input_payload={"file_ids": state.file_ids, "selected_tools": state.selected_tools},
        step=lambda current: execute_selected_tools(current, db),
        output_builder=lambda current: {"tool_results": current.tool_results},
    )
    state = _run_step(
        db=db,
        state=state,
        node_name="write_result",
        tool_name="result_writer",
        input_payload={"task_type": state.task_type, "errors": state.errors},
        step=lambda current: write_result(current),
        output_builder=lambda current: {"final_answer": current.final_answer},
    )

    return state


def _classify(state: AgentState) -> AgentState:
    state.task_type = classify_task(state.user_input)
    return state


def _plan(state: AgentState) -> AgentState:
    state.plan = build_plan(state.task_type)
    return state


def _route(state: AgentState) -> AgentState:
    state.selected_tools = select_tools(state.task_type)
    return state


def _run_step(
    db: Session,
    state: AgentState,
    node_name: str,
    tool_name: str,
    input_payload: dict[str, Any],
    step: AgentStep,
    output_builder: Callable[[AgentState], dict[str, Any] | None],
) -> AgentState:
    started_at = time.perf_counter()
    error_message = None
    output_payload = None
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
        tool_name=tool_name,
        input_payload=input_payload,
        output_payload=output_payload,
        status=status,
        latency_ms=latency_ms,
        error_message=error_message,
    )
    return state


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


def _format_tool_name(selected_tools: list[str]) -> str:
    return ",".join(selected_tools) if selected_tools else "no_tool"
