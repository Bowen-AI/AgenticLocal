from pathlib import Path

from .types import AgentState


class BasicEvaluator:
    def __init__(self, workspace_root: str | Path):
        self.workspace_root = Path(workspace_root).resolve()

    def evaluate(self, state: AgentState) -> dict[str, object]:
        denied_steps = [step for step in state.steps if not step.allowed]
        tool_errors = [step for step in state.steps if step.error]
        return {
            "has_final_answer": state.final_answer is not None,
            "steps": len(state.steps),
            "denied_steps": len(denied_steps),
            "tool_errors": len(tool_errors),
            "workspace_root": str(self.workspace_root),
        }

