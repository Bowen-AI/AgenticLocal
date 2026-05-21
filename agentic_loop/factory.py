from pathlib import Path

from .controller import AgentController
from .logs import JsonlTraceLogger
from .memory import JsonlMemory
from .model import AgentModel, RuleBasedModel
from .ollama_model import OllamaChatModel
from .policy import WorkspacePolicy
from .tools import create_default_tools


def create_controller(
    workspace: str | Path = "sample_workspace",
    memory_path: str | Path = ".agentic-memory.jsonl",
    trace_path: str | Path = ".agentic-trace.jsonl",
    max_steps: int = 8,
    model: AgentModel | None = None,
    provider: str = "rule",
    model_name: str = "gemma3:270m",
    ollama_host: str = "http://127.0.0.1:11434",
) -> AgentController:
    workspace_path = Path(workspace)
    selected_model = model
    if selected_model is None:
        if provider == "rule":
            selected_model = RuleBasedModel()
        elif provider == "ollama":
            selected_model = OllamaChatModel(model=model_name, host=ollama_host)
        else:
            raise ValueError(f"unknown provider: {provider}")

    return AgentController(
        model=selected_model,
        tools=create_default_tools(),
        policy=WorkspacePolicy(workspace_path),
        workspace_root=workspace_path,
        memory=JsonlMemory(memory_path),
        logger=JsonlTraceLogger(trace_path),
        max_steps=max_steps,
    )
