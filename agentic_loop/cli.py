import argparse
import json
import sys
from pathlib import Path

from .chat import run_chat
from .factory import create_controller
from .model import ScriptedModel
from .server import serve
from .types import ModelResponse
from .version import __version__


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "chat":
        return run_chat(argv[1:])
    if argv and argv[0] == "serve":
        return serve(argv[1:])

    parser = argparse.ArgumentParser(prog="agentic-loop")
    parser.add_argument("--version", action="version", version=f"agentic-loop {__version__}")
    parser.add_argument("goal", help="Goal for the agent to execute.")
    parser.add_argument("--workspace", default="sample_workspace")
    parser.add_argument("--memory", default=".agentic-memory.jsonl")
    parser.add_argument("--trace", default=".agentic-trace.jsonl")
    parser.add_argument("--max-steps", type=int, default=8)
    parser.add_argument("--provider", choices=["rule", "ollama"], default="rule")
    parser.add_argument("--model", default="gemma3:270m")
    parser.add_argument("--ollama-host", default="http://127.0.0.1:11434")
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

    controller = create_controller(
        workspace=workspace,
        memory_path=args.memory,
        trace_path=args.trace,
        max_steps=args.max_steps,
        model=model,
        provider=args.provider,
        model_name=args.model,
        ollama_host=args.ollama_host,
    )
    result = controller.run(args.goal)

    if args.json:
        print(
            json.dumps(
                {
                    "final_answer": result.final_answer,
                    "evaluation": result.evaluation,
                    "steps": [step.__dict__ for step in result.state.steps],
                },
                indent=2,
                sort_keys=True,
            )
        )
    else:
        print(result.final_answer)
    return 0
