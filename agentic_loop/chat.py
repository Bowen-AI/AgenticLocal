import argparse

from .factory import create_controller
from .learning import LEARNING_MODES, approve_learning_draft, reject_learning_draft
from .model_selection import (
    DEFAULT_INTERACTIVE_MODEL,
    DEFAULT_INTERACTIVE_PROVIDER,
    DEFAULT_OLLAMA_HOST,
    ModelSelection,
    parse_model_command,
    provider_registry,
    render_model_selection,
)
from .ollama_runtime import ensure_ollama_model_available
from .session import AgentSession


HELP_TEXT = """Commands:
  /help      Show this help.
  /tools     Show available tool names.
  /rules     Show rule toggles.
  /rule on KEY
  /rule off KEY
  /models    Show model providers.
  /model     Show current model.
  /model PROVIDER MODEL
  /model provider=PROVIDER model=MODEL [api_base=URL] [api_key=KEY]
  /workflows Show workflow presets.
  /workflow KEY
  /learn     Show pending learning drafts.
  /learn approve ID
  /learn reject ID
  /skills    Show active procedural skills.
  /skill KEY Show full skill markdown.
  /skill archive KEY
  /loop [goal]
  /search [query]
  /release [goal]
  /history   Show the current session transcript.
  /exit      Quit.
"""


def run_chat(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="agentic-loop chat")
    parser.add_argument("--workspace", default="sample_workspace")
    parser.add_argument("--db", default=".agentic/agentic.db")
    parser.add_argument("--memory", default=None, help="Use legacy JSONL memory at this path.")
    parser.add_argument("--trace", default=None, help="Optional JSONL trace export path.")
    parser.add_argument("--max-steps", type=int, default=8)
    parser.add_argument(
        "--provider",
        choices=["rule", "ollama", "openai", "openai-compatible", "gemini", "localai"],
        default=DEFAULT_INTERACTIVE_PROVIDER,
    )
    parser.add_argument("--model", default=None)
    parser.add_argument("--ollama-host", default=DEFAULT_OLLAMA_HOST)
    parser.add_argument("--api-base", default=None)
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--write-root", action="append", default=[])
    parser.add_argument("--approval-root", action="append", default=[])
    parser.add_argument(
        "--enable-network-tools",
        action="store_true",
        help="Expose search_web, search_news, and fetch_url tools.",
    )
    parser.add_argument("--rule", action="append", default=[], help="Enable a rule for chat runs.")
    parser.add_argument("--no-rule", action="append", default=[], help="Disable a rule for chat runs.")
    parser.add_argument("--workflow", default=None, help="Start chat with a workflow preset.")
    parser.add_argument(
        "--learning",
        choices=sorted(LEARNING_MODES),
        default="draft",
        help="Learning loop mode. Draft records suggestions without auto-activating skills.",
    )
    parser.add_argument(
        "--learning-threshold",
        type=int,
        default=2,
        help="Times a pattern must recur before a procedural skill draft is proposed.",
    )
    args = parser.parse_args(argv)

    write_roots = ["outputs", *args.write_root]
    model_name = args.model
    if args.provider == DEFAULT_INTERACTIVE_PROVIDER and model_name is None:
        model_name = DEFAULT_INTERACTIVE_MODEL
    current_model = ModelSelection.from_values(
        provider=args.provider,
        model_name=model_name,
        ollama_host=args.ollama_host,
        api_base=args.api_base,
        api_key=args.api_key,
    )
    if not ensure_ollama_model_available(current_model):
        return 1

    def make_controller(model_selection: ModelSelection):
        return create_controller(
            workspace=args.workspace,
            memory_path=args.memory,
            trace_path=args.trace,
            db_path=args.db,
            max_steps=args.max_steps,
            provider=model_selection.provider,
            model_name=model_selection.model_name,
            ollama_host=model_selection.ollama_host or args.ollama_host,
            api_base=model_selection.api_base,
            api_key=model_selection.api_key,
            write_roots=write_roots,
            approval_required_roots=args.approval_root,
            enable_network_tools=args.enable_network_tools,
            enabled_rule_keys=args.rule,
            disabled_rule_keys=args.no_rule,
            workflow_key=args.workflow,
            learning_mode=args.learning,
            learning_threshold=args.learning_threshold,
        )

    controller = make_controller(current_model)
    session = AgentSession(controller)
    current_workflow = args.workflow

    print("agentic-loop chat")
    print("Type /help for commands, /exit to quit.")
    print(f"model: {render_model_selection(current_model)}")
    if current_model.provider == "rule":
        print("rule mode is deterministic/offline. Use /models and /model PROVIDER MODEL for a real chat model.")

    while True:
        try:
            user_input = input("> ").strip()
        except EOFError:
            print()
            return 0
        except KeyboardInterrupt:
            print()
            return 0

        if not user_input:
            continue
        if user_input in {"/exit", "/quit"}:
            return 0
        if user_input == "/help":
            print(HELP_TEXT.rstrip())
            continue
        if user_input == "/tools":
            print(", ".join(sorted(controller.tools.names())))
            continue
        if user_input == "/models":
            _print_models()
            continue
        if user_input == "/model":
            print(f"model: {render_model_selection(current_model)}")
            continue
        if user_input.startswith("/model "):
            requested = user_input.split(maxsplit=1)[1].strip()
            try:
                requested_model = parse_model_command(requested, fallback=current_model)
                if not ensure_ollama_model_available(requested_model):
                    continue
                old_history = session.history
                current_model = requested_model
                controller = make_controller(current_model)
                session = AgentSession(
                    controller,
                    history=old_history,
                    session_id=session.session_id,
                    storage=session.storage,
                )
            except ValueError as exc:
                print(f"model error: {exc}")
                continue
            print(f"model: {render_model_selection(current_model)}")
            continue
        if user_input == "/rules":
            _print_rules(controller)
            continue
        if user_input.startswith("/rule "):
            _handle_rule_command(controller, user_input)
            continue
        if user_input == "/workflows":
            _print_workflows(controller)
            continue
        if user_input == "/learn" or user_input.startswith("/learn "):
            _handle_learn_command(controller, user_input)
            continue
        if user_input == "/skills":
            _print_skills(controller)
            continue
        if user_input.startswith("/skill "):
            _handle_skill_command(controller, user_input)
            continue
        if user_input.startswith("/workflow "):
            requested = user_input.split(maxsplit=1)[1].strip()
            if requested in {"off", "none", "clear"}:
                current_workflow = None
                print("workflow cleared")
                continue
            workflow = controller.rule_resolver.workflow(requested)
            if workflow is None:
                print(f"unknown workflow: {requested}")
                continue
            current_workflow = workflow.key
            print(f"workflow active: {workflow.command}")
            continue
        shortcut = _workflow_shortcut(controller, user_input)
        if shortcut is not None:
            workflow, rest = shortcut
            if rest:
                _ask_and_print(session, rest, workflow_key=workflow.key)
            else:
                current_workflow = workflow.key
                print(f"workflow active: {workflow.command}")
            continue
        if user_input == "/history":
            for item in session.transcript():
                print(f"{item['role']}: {item['content']}")
            continue

        _ask_and_print(session, user_input, workflow_key=current_workflow)

    return 0


def _ask_and_print(session: AgentSession, message: str, workflow_key: str | None = None) -> None:
    try:
        result = session.ask(message, workflow_key=workflow_key)
    except Exception as exc:
        print(f"model error: {exc}")
        return
    print(result.final_answer)


def _print_rules(controller) -> None:
    for rule in controller.rule_resolver.rules_with_state():
        status = "on" if rule["enabled"] else "off"
        print(f"{rule['key']} [{status}] - {rule['description']}")


def _print_workflows(controller) -> None:
    for workflow in controller.rule_resolver.workflows():
        print(f"{workflow.command} - {workflow.description}")


def _workflow_shortcut(controller, user_input: str):
    command = user_input.split(maxsplit=1)[0]
    if not command.startswith("/"):
        return None
    workflow = controller.rule_resolver.workflow(command)
    if workflow is None or workflow.command != command:
        return None
    rest = user_input[len(command):].strip()
    return workflow, rest


def _print_models() -> None:
    for item in provider_registry():
        required = "model required" if item.get("model_required") else "model optional"
        api_base = "api_base required" if item.get("api_base_required") else "api_base optional"
        print(f"{item['provider']}: {required}, {api_base} - {item['description']}")


def _handle_rule_command(controller, user_input: str) -> None:
    parts = user_input.split()
    if len(parts) != 3 or parts[1] not in {"on", "off"}:
        print("usage: /rule on KEY or /rule off KEY")
        return
    storage = getattr(controller, "storage", None)
    if storage is None:
        print("rule toggles require SQLite storage")
        return
    rule_key = parts[2]
    known = {rule["key"] for rule in storage.list_rule_registry()}
    if rule_key not in known:
        print(f"unknown rule: {rule_key}")
        return
    storage.set_rule_enabled(rule_key, parts[1] == "on")
    status = "on" if parts[1] == "on" else "off"
    print(f"{rule_key} {status}")


def _handle_learn_command(controller, user_input: str) -> None:
    storage = getattr(controller, "storage", None)
    if storage is None:
        print("learning commands require SQLite storage")
        return
    parts = user_input.split()
    if len(parts) == 1:
        drafts = storage.list_learning_drafts(status="draft")
        if not drafts:
            print("no pending learning drafts")
            return
        for draft in drafts:
            print(f"{draft['id']} [{draft['draft_type']}] {draft['title']} - {draft['status']}")
        return
    if len(parts) != 3 or parts[1] not in {"approve", "reject"}:
        print("usage: /learn, /learn approve ID, or /learn reject ID")
        return
    try:
        draft_id = int(parts[2])
        if parts[1] == "approve":
            result = approve_learning_draft(storage, draft_id)
            draft = result["draft"]
            print(f"approved learning draft {draft['id']}: {draft['title']}")
        else:
            draft = reject_learning_draft(storage, draft_id)
            print(f"rejected learning draft {draft['id']}: {draft['title']}")
    except Exception as exc:
        print(f"learning error: {exc}")


def _print_skills(controller) -> None:
    storage = getattr(controller, "storage", None)
    if storage is None:
        print("skills require SQLite storage")
        return
    skills = storage.list_skills(status="active")
    if not skills:
        print("no active skills")
        return
    for skill in skills:
        triggers = ", ".join(skill.get("triggers") or [])
        print(f"{skill['key']} - {skill['title']} ({triggers})")


def _handle_skill_command(controller, user_input: str) -> None:
    storage = getattr(controller, "storage", None)
    if storage is None:
        print("skills require SQLite storage")
        return
    parts = user_input.split(maxsplit=2)
    if len(parts) == 3 and parts[1] == "archive":
        key = parts[2].strip()
        try:
            skill = storage.archive_skill(key)
            storage.record_event("skill_archived", {"skill_key": key})
            print(f"archived skill {skill['key']}")
        except Exception as exc:
            print(f"skill error: {exc}")
        return
    if len(parts) != 2:
        print("usage: /skill KEY or /skill archive KEY")
        return
    key = parts[1].strip()
    skill = storage.get_skill(key)
    if skill is None:
        print(f"unknown skill: {key}")
        return
    print((skill.get("markdown") or "").rstrip())
