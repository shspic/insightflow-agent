from typing import Any

from app.agents.tool_registry import ToolContext, execute_registered_tool
from app.agents.v2_state import AgentStateV2
from app.models.task_step import TaskStep


class SpecialistAgent:
    agent_type: str

    def execute(self, context: ToolContext, step: TaskStep) -> dict[str, Any]:
        payload = self.build_tool_input(context.state, step)
        return execute_registered_tool(
            context,
            agent_type=self.agent_type,
            tool_name=step.tool_name,
            payload=payload,
        )

    def build_tool_input(self, state: AgentStateV2, step: TaskStep) -> dict[str, Any]:
        return {}


class FileUnderstandingAgent(SpecialistAgent):
    agent_type = "file_understanding_agent"

    def build_tool_input(self, state: AgentStateV2, step: TaskStep) -> dict[str, Any]:
        return {"file_ids": state.selected_file_ids}


class DataAnalysisAgent(SpecialistAgent):
    agent_type = "data_analysis_agent"

    def build_tool_input(self, state: AgentStateV2, step: TaskStep) -> dict[str, Any]:
        parameters = _parameters(step)
        return {
            "file_ids": state.selected_file_ids,
            "generate_charts": parameters.get("generate_charts", True),
        }


class DocumentResearchAgent(SpecialistAgent):
    agent_type = "document_research_agent"

    def build_tool_input(self, state: AgentStateV2, step: TaskStep) -> dict[str, Any]:
        parameters = _parameters(step)
        return {
            "file_ids": state.selected_file_ids,
            "query": state.clarified_request,
            "top_k": parameters.get("top_k", 5),
            "retrieval_mode": parameters.get("retrieval_mode", "auto"),
        }


class ReportAgent(SpecialistAgent):
    agent_type = "report_agent"

    def build_tool_input(self, state: AgentStateV2, step: TaskStep) -> dict[str, Any]:
        return {"task_id": state.task_id}


class QualityReviewAgent(SpecialistAgent):
    agent_type = "quality_review_agent"

    def build_tool_input(self, state: AgentStateV2, step: TaskStep) -> dict[str, Any]:
        return {"task_id": state.task_id}


SPECIALIST_AGENTS = {
    agent.agent_type: agent
    for agent in [
        FileUnderstandingAgent(),
        DataAnalysisAgent(),
        DocumentResearchAgent(),
        ReportAgent(),
        QualityReviewAgent(),
    ]
}


def get_specialist_agent(agent_type: str) -> SpecialistAgent:
    try:
        return SPECIALIST_AGENTS[agent_type]
    except KeyError as exc:
        raise ValueError(f"未注册专业 Agent：{agent_type}") from exc


def _parameters(step: TaskStep) -> dict[str, Any]:
    import json

    try:
        data = json.loads(step.input_json or "{}")
    except json.JSONDecodeError:
        return {}
    return data.get("parameters", {}) if isinstance(data, dict) else {}
