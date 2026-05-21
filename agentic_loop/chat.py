import argparse

from .factory import create_controller
from .session import AgentSession


HELP_TEXT = """Commands:
  /help      Show this help.
  /tools     Show available tool names.
  /history   Show the current session transcript.
  /exit      Quit.
"""


def run_chat(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="agentic-loop chat")
    parser.add_argument("--workspace", default="sample_workspace")
    parser.add_argument("--memory", default=".agentic-memory.jsonl")
    parser.add_argument("--trace", default=".agentic-trace.jsonl")
    parser.add_argument("--max-steps", type=int, default=8)
    parser.add_argument("--provider", choices=["rule", "ollama"], default="rule")
    parser.add_argument("--model", default="gemma3:270m")
    parser.add_argument("--ollama-host", default="http://127.0.0.1:11434")
    args = parser.parse_args(argv)

    controller = create_controller(
        workspace=args.workspace,
        memory_path=args.memory,
        trace_path=args.trace,
        max_steps=args.max_steps,
        provider=args.provider,
        model_name=args.model,
        ollama_host=args.ollama_host,
    )
    session = AgentSession(controller)

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
        if user_input == "/history":
            for item in session.transcript():
                print(f"{item['role']}: {item['content']}")
            continue

        result = session.ask(user_input)
        print(result.final_answer)

    return 0
