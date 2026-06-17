from langgraph.graph import END, START, StateGraph
from sqlalchemy.orm import Session

from app.agents.nodes import build_node_map
from app.agents.state import AgentStateDict


def build_agent_workflow(db: Session):
    workflow = StateGraph(AgentStateDict)
    node_map = build_node_map(db)

    for node_name, node_func in node_map.items():
        workflow.add_node(node_name, node_func)

    workflow.add_edge(START, "classify_task")
    workflow.add_edge("classify_task", "plan_task")
    workflow.add_edge("plan_task", "route_tools")
    workflow.add_edge("route_tools", "execute_tool")
    workflow.add_edge("execute_tool", "write_result")
    workflow.add_edge("write_result", "save_result")
    workflow.add_edge("save_result", END)

    return workflow.compile()
