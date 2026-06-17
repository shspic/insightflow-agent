from dataclasses import dataclass, field
from typing import Any
from typing import TypedDict


@dataclass
class AgentState:
    task_id: int
    user_input: str
    file_ids: list[int]
    task_type: str = "unsupported"
    plan: list[str] = field(default_factory=list)
    selected_tools: list[str] = field(default_factory=list)
    tool_results: dict[str, Any] = field(default_factory=dict)
    final_answer: str | None = None
    errors: list[str] = field(default_factory=list)


class AgentStateDict(TypedDict, total=False):
    task_id: int
    user_input: str
    file_ids: list[int]
    task_type: str
    plan: list[str]
    selected_tools: list[str]
    tool_results: dict[str, Any]
    final_answer: str | None
    errors: list[str]


def create_initial_state(task_id: int, user_input: str, file_ids: list[int]) -> AgentStateDict:
    return {
        "task_id": task_id,
        "user_input": user_input,
        "file_ids": file_ids,
        "task_type": "unsupported",
        "plan": [],
        "selected_tools": [],
        "tool_results": {},
        "final_answer": None,
        "errors": [],
    }


def state_from_dict(state: AgentStateDict) -> AgentState:
    return AgentState(
        task_id=state["task_id"],
        user_input=state["user_input"],
        file_ids=state.get("file_ids", []),
        task_type=state.get("task_type", "unsupported"),
        plan=state.get("plan", []),
        selected_tools=state.get("selected_tools", []),
        tool_results=state.get("tool_results", {}),
        final_answer=state.get("final_answer"),
        errors=state.get("errors", []),
    )


def state_to_dict(state: AgentState) -> AgentStateDict:
    return {
        "task_id": state.task_id,
        "user_input": state.user_input,
        "file_ids": state.file_ids,
        "task_type": state.task_type,
        "plan": state.plan,
        "selected_tools": state.selected_tools,
        "tool_results": state.tool_results,
        "final_answer": state.final_answer,
        "errors": state.errors,
    }
