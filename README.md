# Agentic AI Loop

This repository contains a dependency-free implementation of a minimal agentic
AI runtime:

```text
agent = model + state + tools + policy loop
```

Current version: `0.1.0`

Start here:

- [Agentic AI: The Loop](docs/design/agentic-ai-loop.md)

## Run The Demo

Start an interactive agent chat:

```bash
python3 -m agentic_loop chat
```

List files through the agent loop:

```bash
python3 -m agentic_loop "List files in the workspace."
```

Inspect a CSV through a tool call:

```bash
python3 -m agentic_loop "Inspect data/sample.csv as a dataset."
```

Write only to the allowed `outputs/` folder:

```bash
python3 -m agentic_loop "Write a note saying hello from the agent."
```

Return structured JSON:

```bash
python3 -m agentic_loop "Inspect data/sample.csv" --json
```

Show the CLI version:

```bash
python3 -m agentic_loop --version
```

Start the local HTTP agent service:

```bash
python3 -m agentic_loop serve --host 127.0.0.1 --port 8765
```

Then open the embedded voice mode:

```text
http://127.0.0.1:8765/voice
```

Or call it from another terminal:

```bash
curl -s http://127.0.0.1:8765/health
curl -s -X POST http://127.0.0.1:8765/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"Inspect data/sample.csv as a dataset."}'
```

## Verification

Run the full release check. This is the main command for a normal release:

```bash
scripts/check_release.sh
```

Run optional checks when the environment supports them:

```bash
python3 scripts/smoke_server.py
python3 scripts/smoke_ollama.py --model gemma3:270m
```

The server smoke test opens a local loopback socket. Some sandboxes block that,
so it is separate from the default release check.

The Ollama smoke test requires Ollama to be running and the requested model to
be installed. For Gemma 3 270M:

```bash
ollama pull gemma3:270m
```

Run the full smoke test, including unit tests and real CLI executions:

```bash
scripts/smoke_test.sh
```

Run only the unit tests:

```bash
python3 -m unittest discover -s tests -v
```

Current coverage checks:

- loop/controller execution
- tool calls
- workspace policy enforcement
- denied unsafe reads/writes
- interactive chat session state
- JSONL memory remember/recall
- CSV inspection
- max-step stopping
- structured result shape
- Ollama adapter parsing/fallback behavior

## Package

This project is dependency-free and targets Python 3.11+.

Run without installing:

```bash
python3 -m agentic_loop "List files in the workspace."
```

Install as an editable local package when `pip` is available:

```bash
python3 -m pip install -e .
agentic-loop "Inspect data/sample.csv as a dataset."
```

## Code Map

```text
agentic_loop/
  controller.py  # loop
  model.py       # model interface, scripted model, deterministic demo model
  ollama_model.py # Ollama chat adapter
  tools.py       # tool schemas and implementations
  policy.py      # permissions
  context.py     # context construction
  memory.py      # JSONL long-term memory
  state.py       # agent state
  evals.py       # completion/safety evaluation
  logs.py        # JSONL traces
  cli.py         # runnable command-line demo
  chat.py        # interactive terminal chat
  server.py      # local HTTP service
  voice.py       # embedded browser voice page
  session.py     # multi-turn chat sessions
  factory.py      # controller construction
```

## Architecture Direction

See [Architecture Decision](docs/architecture-decision.md).

Related notes:

- [OpenAI Agents SDK compatibility](docs/openai-sdk-compatibility.md)
- [Ollama Gemma check](docs/ollama-gemma-check.md)
- [Voice agents](docs/voice-agents.md)
