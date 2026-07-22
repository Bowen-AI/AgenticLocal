import os
from pathlib import Path

from .context import ContextBuilder
from .controller import AgentController
from .logs import CompositeTraceLogger, JsonlTraceLogger, SQLiteTraceLogger
from .memory import JsonlMemory
from .model_selection import ModelSelection
from .model import AgentModel, RuleBasedModel
from .ollama_model import OllamaChatModel
from .policy import WorkspaceAccessConfig, WorkspacePolicy
from .providers.localai import LocalAIChatModel
from .providers.openai_compatible import OpenAICompatibleChatModel
from .rules import RuleResolver
from .storage import SQLiteStore
from .tools import ToolContext, ToolRegistry, WebClient, create_default_tools


def create_controller(
    workspace: str | Path = "sample_workspace",
    memory_path: str | Path | None = None,
    trace_path: str | Path | None = None,
    db_path: str | Path | None = ".agentic/agentic.db",
    max_steps: int = 8,
    model: AgentModel | None = None,
    provider: str = "rule",
    model_name: str | None = None,
    ollama_host: str = "http://127.0.0.1:11434",
    ollama_think: bool | str | None = False,
    api_base: str | None = None,
    api_key: str | None = None,
    read_roots: list[str | Path] | tuple[str | Path, ...] | None = None,
    write_roots: list[str | Path] | tuple[str | Path, ...] | None = None,
    approval_required_roots: list[str | Path] | tuple[str | Path, ...] | None = None,
    storage: SQLiteStore | None = None,
    enable_network_tools: bool = False,
    web_client: WebClient | None = None,
    tools: ToolRegistry | None = None,
    allowed_tools: set[str] | None = None,
    tool_context: ToolContext | None = None,
    enabled_rule_keys: list[str] | tuple[str, ...] | set[str] | None = None,
    disabled_rule_keys: list[str] | tuple[str, ...] | set[str] | None = None,
    workflow_key: str | None = None,
    learning_mode: str = "draft",
    learning_threshold: int = 2,
    system_prompt: str | None = None,
) -> AgentController:
    workspace_path = Path(workspace)
    registry = tools or create_default_tools(enable_network=enable_network_tools)
    selected_storage = storage
    if selected_storage is None and db_path is not None:
        selected_storage = SQLiteStore(db_path)
    if selected_storage is not None:
        selected_storage.seed_tool_registry(registry.metadata())
        selected_storage.seed_default_ui_registry()
        selected_storage.seed_default_rule_registry()
        selected_storage.seed_default_workflow_registry()

    model_selection = ModelSelection.from_values(
        provider=provider,
        model_name=model_name,
        ollama_host=ollama_host,
        api_base=api_base,
        api_key=api_key,
    )
    selected_model = model
    if selected_model is None:
        if model_selection.provider == "rule":
            selected_model = RuleBasedModel()
        elif model_selection.provider == "ollama":
            selected_model = OllamaChatModel(
                model=model_selection.model_name or "",
                host=model_selection.ollama_host or "http://127.0.0.1:11434",
                think=ollama_think,
            )
        elif model_selection.provider in {"openai", "openai-compatible"}:
            selected_model = OpenAICompatibleChatModel(
                model=model_selection.model_name or "",
                base_url=model_selection.api_base or "https://api.openai.com/v1",
                api_key=model_selection.api_key,
            )
        elif model_selection.provider == "gemini":
            selected_model = OpenAICompatibleChatModel(
                model=model_selection.model_name or "",
                base_url=model_selection.api_base or "",
                api_key=model_selection.api_key or os.environ.get("GEMINI_API_KEY", ""),
            )
        elif model_selection.provider == "localai":
            selected_model = LocalAIChatModel(
                model=model_selection.model_name or "",
                host=model_selection.api_base or "http://127.0.0.1:8080/v1",
                api_key=model_selection.api_key,
            )
        elif model_selection.provider in {"mlx", "mlx-lm"}:
            from .providers.mlx_lm import MlxLmChatModel

            selected_model = MlxLmChatModel(model=model_selection.model_name or "")
        else:
            raise ValueError(f"unknown provider: {model_selection.provider}")

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
        context_builder=ContextBuilder(system_prompt=system_prompt) if system_prompt else None,
        tools=registry,
        policy=WorkspacePolicy(
            workspace_path,
            allowed_tools=allowed_tools or registry.names(),
            access=access,
        ),
        workspace_root=workspace_path,
        memory=memory,
        logger=logger,
        max_steps=max_steps,
        storage=selected_storage,
        web_client=web_client,
        rule_resolver=RuleResolver(selected_storage),
        enabled_rule_keys=enabled_rule_keys,
        disabled_rule_keys=disabled_rule_keys,
        workflow_key=workflow_key,
        tool_context=tool_context,
        learning_mode=learning_mode,
        learning_threshold=learning_threshold,
    )
