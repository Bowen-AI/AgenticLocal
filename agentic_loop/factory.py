from pathlib import Path

from .controller import AgentController
from .logs import CompositeTraceLogger, JsonlTraceLogger, SQLiteTraceLogger
from .memory import JsonlMemory
from .model import AgentModel, RuleBasedModel
from .ollama_model import OllamaChatModel
from .policy import WorkspaceAccessConfig, WorkspacePolicy
from .providers.localai import LocalAIChatModel
from .providers.openai_compatible import OpenAICompatibleChatModel
from .storage import SQLiteStore
from .tools import WebClient, create_default_tools


def create_controller(
    workspace: str | Path = "sample_workspace",
    memory_path: str | Path | None = None,
    trace_path: str | Path | None = None,
    db_path: str | Path | None = ".agentic/agentic.db",
    max_steps: int = 8,
    model: AgentModel | None = None,
    provider: str = "rule",
    model_name: str = "gemma3:270m",
    ollama_host: str = "http://127.0.0.1:11434",
    api_base: str | None = None,
    api_key: str | None = None,
    read_roots: list[str | Path] | tuple[str | Path, ...] | None = None,
    write_roots: list[str | Path] | tuple[str | Path, ...] | None = None,
    approval_required_roots: list[str | Path] | tuple[str | Path, ...] | None = None,
    storage: SQLiteStore | None = None,
    enable_network_tools: bool = False,
    web_client: WebClient | None = None,
) -> AgentController:
    workspace_path = Path(workspace)
    registry = create_default_tools(enable_network=enable_network_tools)
    selected_storage = storage
    if selected_storage is None and db_path is not None:
        selected_storage = SQLiteStore(db_path)
    if selected_storage is not None:
        selected_storage.seed_tool_registry(registry.metadata())
        selected_storage.seed_default_ui_registry()

    selected_model = model
    if selected_model is None:
        if provider == "rule":
            selected_model = RuleBasedModel()
        elif provider == "ollama":
            selected_model = OllamaChatModel(model=model_name, host=ollama_host)
        elif provider in {"openai", "openai-compatible"}:
            selected_model = OpenAICompatibleChatModel(
                model=model_name,
                base_url=api_base or "https://api.openai.com/v1",
                api_key=api_key,
            )
        elif provider == "localai":
            selected_model = LocalAIChatModel(
                model=model_name,
                host=api_base or "http://127.0.0.1:8080/v1",
                api_key=api_key,
            )
        else:
            raise ValueError(f"unknown provider: {provider}")

    memory = JsonlMemory(memory_path) if memory_path is not None else selected_storage
    loggers = []
    if trace_path is not None:
        loggers.append(JsonlTraceLogger(trace_path))
    if selected_storage is not None:
        loggers.append(SQLiteTraceLogger(selected_storage))
    logger = CompositeTraceLogger(*loggers) if loggers else JsonlTraceLogger()
    access = WorkspaceAccessConfig(
        workspace_path,
        read_roots=read_roots,
        write_roots=write_roots,
        approval_required_roots=approval_required_roots,
    )

    return AgentController(
        model=selected_model,
        tools=registry,
        policy=WorkspacePolicy(workspace_path, access=access),
        workspace_root=workspace_path,
        memory=memory,
        logger=logger,
        max_steps=max_steps,
        storage=selected_storage,
        web_client=web_client,
    )
