from sqlalchemy.orm import Session

from app.agents.graph import build_agent_workflow
from app.agents.state import AgentState, create_initial_state, state_from_dict


def run_langgraph_agent(task_id: int, user_input: str, file_ids: list[int], db: Session) -> AgentState:
    workflow = build_agent_workflow(db)
    output_state = workflow.invoke(create_initial_state(task_id, user_input, file_ids))
    return state_from_dict(output_state)


def run_basic_agent(task_id: int, user_input: str, file_ids: list[int], db: Session) -> AgentState:
    return run_langgraph_agent(task_id=task_id, user_input=user_input, file_ids=file_ids, db=db)
