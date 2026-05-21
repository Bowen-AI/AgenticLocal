import argparse
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agentic_loop.factory import create_controller
from agentic_loop.ollama_model import OllamaChatModel
from agentic_loop.types import Message


def get_json(url):
    with urllib.request.urlopen(url, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="http://127.0.0.1:11434")
    parser.add_argument("--model", default="gemma3:270m")
    args = parser.parse_args(argv)

    host = args.host.rstrip("/")
    tags = get_json(f"{host}/api/tags")
    model_names = {model["name"] for model in tags.get("models", [])}
    if args.model not in model_names:
        raise SystemExit(f"missing Ollama model {args.model}; run: ollama pull {args.model}")

    direct_model = OllamaChatModel(model=args.model, host=host, use_tools=False)
    direct = direct_model.respond(
        [Message(role="user", content="Reply with exactly: OK")],
        [],
        "",
    )
    if not direct.final_answer:
        raise SystemExit("Ollama direct model call returned no final answer")

    controller = create_controller(
        provider="ollama",
        model_name=args.model,
        ollama_host=host,
        trace_path="/tmp/agentic-loop-ollama-smoke-trace.jsonl",
        memory_path="/tmp/agentic-loop-ollama-smoke-memory.jsonl",
    )
    chat_result = controller.run("Reply with exactly: OK")
    inspect_result = controller.run("Inspect data/sample.csv as a dataset.")

    native_tool_calling = any(step.tool_name for step in inspect_result.state.steps)
    result = {
        "model": args.model,
        "ollama_chat_works": "OK" in chat_result.final_answer,
        "native_tool_calling_for_inspect": native_tool_calling,
        "inspect_final_answer": inspect_result.final_answer,
    }
    print(json.dumps(result, indent=2, sort_keys=True))

    if not result["ollama_chat_works"]:
        raise SystemExit("Gemma/Ollama chat did not produce expected OK response")

    print("Ollama smoke test passed.")


if __name__ == "__main__":
    main()
