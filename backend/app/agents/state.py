from dataclasses import dataclass, field
from typing import Any


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
