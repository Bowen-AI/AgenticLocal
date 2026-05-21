from .types import AgentState


def new_state(goal: str) -> AgentState:
    return AgentState(goal=goal)

