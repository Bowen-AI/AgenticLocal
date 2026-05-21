import argparse

from .factory import create_controller
from .session import AgentSession


HELP_TEXT = """Commands:
  /help      Show this help.
  /tools     Show available tool names.
  /rules     Show rule toggles.
  /rule on KEY
  /rule off KEY
  /workflows Show workflow presets.
  /workflow KEY
  /loop [goal]
  /search [query]
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
        default="rule",
    )
    parser.add_argument("--model", default=None)
    parser.add_argument("--ollama-host", default="http://127.0.0.1:11434")
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
    args = parser.parse_args(argv)

    write_roots = ["outputs", *args.write_root]
    controller = create_controller(
        workspace=args.workspace,
        memory_path=args.memory,
        trace_path=args.trace,
        db_path=args.db,
        max_steps=args.max_steps,
        provider=args.provider,
        model_name=args.model,
        ollama_host=args.ollama_host,
        api_base=args.api_base,
        api_key=args.api_key,
        write_roots=write_roots,
        approval_required_roots=args.approval_root,
        enable_network_tools=args.enable_network_tools,
        enabled_rule_keys=args.rule,
        disabled_rule_keys=args.no_rule,
        workflow_key=args.workflow,
    )
    session = AgentSession(controller)
    current_workflow = args.workflow

    print("agentic-loop chat")
    print("Type /help for commands, /exit to quit.")

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
        if user_input == "/rules":
            _print_rules(controller)
            continue
        if user_input.startswith("/rule "):
            _handle_rule_command(controller, user_input)
            continue
        if user_input == "/workflows":
            _print_workflows(controller)
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
        if user_input == "/loop" or user_input.startswith("/loop "):
            rest = user_input[len("/loop"):].strip()
            if rest:
                result = session.ask(rest, workflow_key="loop")
                print(result.final_answer)
            else:
                current_workflow = "loop"
                print("workflow active: /loop")
            continue
        if user_input == "/search" or user_input.startswith("/search "):
            rest = user_input[len("/search"):].strip()
            if rest:
                result = session.ask(rest, workflow_key="search")
                print(result.final_answer)
            else:
                current_workflow = "search"
                print("workflow active: /search")
            continue
        if user_input == "/history":
            for item in session.transcript():
                print(f"{item['role']}: {item['content']}")
            continue

        result = session.ask(user_input, workflow_key=current_workflow)
        print(result.final_answer)

    return 0


def _print_rules(controller) -> None:
    for rule in controller.rule_resolver.rules_with_state():
        status = "on" if rule["enabled"] else "off"
        print(f"{rule['key']} [{status}] - {rule['description']}")


def _print_workflows(controller) -> None:
    for workflow in controller.rule_resolver.workflows():
        print(f"{workflow.command} - {workflow.description}")


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
