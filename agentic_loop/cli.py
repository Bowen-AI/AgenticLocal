import argparse
import json
import sys
from pathlib import Path

from .chat import run_chat
from .client import run_client
from .factory import create_controller
from .model_selection import ModelSelection, provider_registry
from .model import ScriptedModel
from .ollama_runtime import ensure_ollama_model_available
from .rules import RuleResolver
from .server import serve
from .storage import SQLiteStore
from .types import ModelResponse
from .version import __version__


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "chat":
        return run_chat(argv[1:])
    if argv and argv[0] == "client":
        return run_client(argv[1:])
    if argv and argv[0] == "serve":
        return serve(argv[1:])

    parser = argparse.ArgumentParser(prog="agentic-loop")
    parser.add_argument("--version", action="version", version=f"agentic-loop {__version__}")
    parser.add_argument("goal", nargs="?", help="Goal for the agent to execute.")
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
    parser.add_argument("--rule", action="append", default=[], help="Enable a rule for this run.")
    parser.add_argument("--no-rule", action="append", default=[], help="Disable a rule for this run.")
    parser.add_argument("--workflow", default=None, help="Run with a workflow preset such as loop or search.")
    parser.add_argument("--rules", action="store_true", help="List available rules.")
    parser.add_argument("--workflows", action="store_true", help="List available workflows.")
    parser.add_argument("--models", action="store_true", help="List available model providers.")
    parser.add_argument("--json", action="store_true", help="Print structured result JSON.")
    parser.add_argument(
        "--scripted-tool-call",
        help=(
            "JSON object with name and arguments. Intended for smoke tests that "
            "need to force one exact tool call through the normal controller."
        ),
    )
    parser.add_argument(
        "--scripted-final",
        default="Scripted run finished.",
        help="Final answer emitted after a scripted tool call.",
    )
    args = parser.parse_args(argv)

    if args.models:
        for item in provider_registry():
            required = "model required" if item.get("model_required") else "model optional"
            api_base = "api_base required" if item.get("api_base_required") else "api_base optional"
            print(f"{item['provider']}: {required}, {api_base} - {item['description']}")
        return 0

    if args.rules or args.workflows:
        storage = SQLiteStore(args.db)
        storage.seed_default_rule_registry()
        storage.seed_default_workflow_registry()
        resolver = RuleResolver(storage)
        if args.rules:
            for rule in resolver.rules_with_state():
                status = "on" if rule["enabled"] else "off"
                print(f"{rule['key']} [{status}] - {rule['description']}")
        if args.workflows:
            for workflow in resolver.workflows():
                print(f"{workflow.command} - {workflow.description}")
        return 0

    if not args.goal:
        parser.error("goal is required unless --rules, --workflows, or --models is used")

    workspace = Path(args.workspace)
    model = None
    if args.scripted_tool_call:
        call = json.loads(args.scripted_tool_call)
        model = ScriptedModel(
            [
                ModelResponse.call(
                    call["name"],
                    call.get("arguments", {}),
                    call.get("id", "scripted_call"),
                ),
                ModelResponse.final(args.scripted_final),
            ]
        )

    write_roots = ["outputs", *args.write_root]
    if model is None and args.provider == "ollama" and args.model is not None:
        model_selection = ModelSelection.from_values(
            provider=args.provider,
            model_name=args.model,
            ollama_host=args.ollama_host,
            api_base=args.api_base,
            api_key=args.api_key,
        )
        if not ensure_ollama_model_available(model_selection):
            return 1

    controller = create_controller(
        workspace=workspace,
        memory_path=args.memory,
        trace_path=args.trace,
        db_path=args.db,
        max_steps=args.max_steps,
        model=model,
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
    result = controller.run(args.goal)

    if args.json:
        print(
            json.dumps(
                {
                    "final_answer": result.final_answer,
                    "evaluation": result.evaluation,
                    "run_id": result.run_id,
                    "steps": [step.__dict__ for step in result.state.steps],
                },
                indent=2,
                sort_keys=True,
            )
        )
    else:
        print(result.final_answer)
    return 0
