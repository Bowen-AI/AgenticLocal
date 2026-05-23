# Agentic AI Loop

This repository contains a dependency-free implementation of a minimal agentic
AI runtime:

```text
agent = model + state + tools + policy loop
```

Current version: `0.1.0`

Start here:

- [Published Project Page](https://bowen-ai.github.io/AgenticLocal/)
- [Local Project Page Source](docs/index.html)
- [Agentic AI: The Loop](docs/design/agentic-ai-loop.md)
- [Install Guide](docs/install.md)
- [Use Cases](docs/use-cases.md)
- [Example Screenshots](docs/example-screenshots.md)
- [GitHub Pages Deploy](docs/github-pages.md)

## Quick Install

Install the `agentic-loop` command on Linux or macOS with the bootstrap script:

```bash
curl -fsSL https://raw.githubusercontent.com/Bowen-AI/AgenticLocal/main/scripts/install.sh \
  -o install-agentic-loop.sh
bash install-agentic-loop.sh --with-ollama
agentic-loop --version
```

Or run it directly:

```bash
curl -fsSL https://raw.githubusercontent.com/Bowen-AI/AgenticLocal/main/scripts/install.sh \
  | bash -s -- --with-ollama
```

From a local checkout, use the same installer:

```bash
scripts/install.sh
agentic-loop --version
```

The installer creates an isolated environment under
`~/.local/share/agentic-loop`, writes a launcher to `~/.local/bin`, prompts for
Ollama when it is missing, and pulls the default `qwen3.5:4b-mlx` model when
Ollama is available. Use `--no-model-pull` to skip the model download.

Common install modes:

```bash
scripts/install.sh --with-ollama
scripts/install.sh --ollama-model qwen3.5:4b-mlx
scripts/install.sh --no-ollama
```

## Run The Demo

Start an interactive agent chat:

```bash
python3 -m agentic_loop chat
```

Interactive chat defaults to Ollama with `qwen3.5:4b-mlx`; when a selected
startup model or `/model` switch is missing, the CLI asks whether to download it
before continuing. Start chat with opt-in public web/news tools:

```bash
python3 -m agentic_loop chat --enable-network-tools
```

Then try:

```text
Search the internet for agentic AI.
Search news about robotics.
Fetch https://example.com and summarize it.
```

List files through the agent loop:

```bash
python3 -m agentic_loop "List files in the workspace."
```

Inspect a CSV through a tool call:

```bash
python3 -m agentic_loop "Inspect data/sample.csv as a dataset."
```

Write to the default configured `outputs/` write root:

```bash
python3 -m agentic_loop "Write a note saying hello from the agent."
```

Add another named write root:

```bash
python3 -m agentic_loop \
  --write-root drafts \
  "Save a draft note."
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

The service defaults to Ollama with `qwen3.5:4b-mlx`, but clients can choose provider and
model per request or per session. Use `--provider rule` when you want the
dependency-free deterministic provider.

Public web/news/fetch tools are enabled by default for the local service. Start
without those network tools when you want a narrower server:

```bash
python3 -m agentic_loop serve \
  --host 127.0.0.1 \
  --port 8765 \
  --disable-network-tools
```

Then open the embedded voice mode:

```text
http://127.0.0.1:8765/voice
```

Or call it from another terminal:

```bash
curl -s http://127.0.0.1:8765/health
curl -s http://127.0.0.1:8765/events
curl -N "http://127.0.0.1:8765/events?follow=1&timeout=30"
curl -s http://127.0.0.1:8765/memory
curl -s http://127.0.0.1:8765/registry/models
curl -s http://127.0.0.1:8765/registry/rules
curl -s http://127.0.0.1:8765/registry/workflows
curl -s -X POST http://127.0.0.1:8765/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"Inspect data/sample.csv as a dataset.","workflow":"loop"}'
```

Choose a served model per request:

```bash
curl -s -X POST http://127.0.0.1:8765/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"hello","model":{"provider":"ollama","name":"your-local-model"}}'

curl -s -X POST http://127.0.0.1:8765/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"hello","model":{"provider":"openai","name":"your-openai-model","api_key":"..."}}'
```

Use the CLI against a running server:

```bash
python3 -m agentic_loop client --models
python3 -m agentic_loop client --provider ollama --model your-local-model "hello"
```

By default, durable app state is stored in:

```text
.agentic/agentic.db
```

That SQLite database stores sessions, messages, run steps, long-term memory,
events/traces, tool/UI registry metadata, and rule/workflow registry metadata.
JSONL memory and trace files are still available as optional legacy/export
paths through `--memory` and `--trace`.

Rules and workflows can be listed from the CLI:

```bash
python3 -m agentic_loop --rules
python3 -m agentic_loop --workflows
python3 -m agentic_loop --models
python3 -m agentic_loop --workflow loop "Inspect data/sample.csv"
python3 -m agentic_loop chat --enable-network-tools
```

Inside chat, use `/rules`, `/rule on max_effort`, `/models`,
`/model ollama qwen3.5:4b-mlx`, `/loop`, `/search`, and `/release`.

When chat starts without `--provider`, it uses `--provider ollama --model qwen3.5:4b-mlx`.
Use `--provider rule` for deterministic offline demos and tool-loop tests.
Explicit Ollama model choices in chat, one-shot runs, serving, and local client
requests prompt to download the model first when it is not already installed.

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

Run the richer end-to-end showcase:

```bash
python3 scripts/showcase_e2e.py
```

This demonstrates CLI runs, SQLite memory across processes, configurable write
roots, approval-required roots, HTTP chat, durable API views, registries, SSE
events, and provider/voice adapter boundaries. It starts a local loopback HTTP
server for the HTTP/SSE section.

Run only the unit tests:

```bash
python3 -m unittest discover -s tests -v
```

Current coverage checks:

- loop/controller execution
- repeated identical tool-call loop guard
- tool calls
- opt-in public web/news/fetch tools
- workspace policy enforcement
- denied unsafe reads/writes
- configurable write roots
- approval-required write roots
- interactive chat session state
- SQLite memory remember/recall
- durable server sessions
- persisted workflow events
- tool/UI/rule/workflow registry metadata
- SSE event formatting
- CSV inspection
- max-step stopping
- structured result shape
- provider adapter selection
- voice adapter interface
- Ollama adapter parsing/fallback behavior

## Package

This project is dependency-free and targets Python 3.11+.

Run without installing:

```bash
python3 -m agentic_loop "List files in the workspace."
```

Install the `agentic-loop` command from a Linux or macOS checkout:

```bash
scripts/install.sh
agentic-loop --version
```

The installer prefers an isolated venv under `~/.local/share/agentic-loop` and
creates a launcher in `~/.local/bin`. If your system Python lacks venv/pip
support, it prints the platform package to install.

Ollama is a system application, not a Python wheel dependency. The installer
will prompt to install Ollama when it is missing and pulls the default model
when Ollama is available:

```bash
scripts/install.sh --with-ollama
scripts/install.sh --ollama-model qwen3.5:4b-mlx
scripts/install.sh --no-model-pull
scripts/install.sh --no-ollama
```

Build release artifacts:

```bash
scripts/package_release.sh
ls dist/
```

This emits a universal wheel and source tarball without requiring `pip`,
`wheel`, or `python -m build`.

Install as an editable local package when `pip` is already available:

```bash
python3 -m pip install -e .
agentic-loop "Inspect data/sample.csv as a dataset."
```

CI runs `scripts/check_release.sh` on Linux and macOS for Python 3.11 and 3.12.

## Components

```text
agentic_loop/
  controller.py  # loop
  model.py       # model interface, scripted model, deterministic demo model
  ollama_model.py # Ollama chat adapter
  providers/     # OpenAI-compatible and LocalAI adapter scaffolding
  tools.py       # tool schemas and implementations
  policy.py      # permissions
  context.py     # context construction
  memory.py      # JSONL long-term memory
  storage.py     # SQLite sessions, events, memory, traces, registries
  state.py       # agent state
  evals.py       # completion/safety evaluation
  logs.py        # JSONL traces
  cli.py         # runnable command-line demo
  chat.py        # interactive terminal chat
  server.py      # local HTTP service
  voice.py       # embedded browser voice page
  voice_adapters.py # provider-neutral voice adapter interfaces
  session.py     # multi-turn chat sessions
  factory.py      # controller construction
```

## System Diagram

The main runtime shape is:

```text
User / UI
  -> CLI, terminal chat, HTTP API, browser voice page
  -> Agent Runtime
       -> Context Builder
       -> Model Adapter
       -> Rule Resolver
       -> Workspace Policy
       -> Tool Registry
       -> Event Logger
       -> Evaluator
  -> SQLite Storage
       -> sessions, messages, memory, events, traces, registries
  -> Workspace Files
       -> read roots, write roots, approval-gated roots
```

## Architecture Direction

See [Architecture Decision](docs/architecture-decision.md).

Detailed architecture:

```text
User / UI
  -> Terminal chat, HTTP chat, browser voice page, tool timeline

HTTP API
  -> POST /chat
  -> POST /run
  -> POST /models/select
  -> GET /events        SSE event stream snapshot
  -> GET /events?follow=1&timeout=30
  -> GET /tools         tool schemas + registry metadata
  -> GET /memory        long-term memory records
  -> GET /sessions      durable session list
  -> GET /registry/ui   UI component registry metadata
  -> GET /registry/rules
  -> GET /registry/workflows
  -> GET /registry/models

Agent Runtime
  -> Context Builder
  -> Brain / Model Adapter
       - Rule model
       - Ollama
       - OpenAI-compatible
       - Gemini/OpenAI-compatible endpoints
       - LocalAI
       - other provider API keys through the adapter boundary
  -> Policy / Approval Engine
       - configured read roots
       - configured write roots
       - approval-required roots
       - active rule checks
       - symlink/path escape checks
  -> Tool Registry
       - local file tools
       - CSV inspection
       - memory tools
       - opt-in web/news/fetch tools
       - future paper, dataset, MCP tools
  -> Event Logger
  -> Evaluator

Storage
  -> SQLite .agentic/agentic.db
       - sessions + messages
       - working state + steps
       - long-term memory
       - tool registry metadata
       - UI registry metadata
       - rule registry metadata + settings
       - workflow registry metadata
       - traces/events
  -> Workspace files
       - configured read roots
       - configured write roots
       - approval-gated risky roots

Voice
  -> Browser Web Speech pipeline now
  -> VoiceAdapter interface for realtime providers later
       - Gemini Live Voice example
       - OpenAI Realtime example
       - same policy/tools/memory/runtime underneath
```

Memory/state split:

```text
Short-term context
  Prompt messages sent to the model on the current turn.

Working memory
  AgentState and step/task state for the current run.

Session memory
  Conversation transcript persisted by session_id in SQLite.

Long-term memory
  Deliberate remember/recall facts persisted across sessions.

Retrieval memory
  Future searchable project/code/docs chunks, separate from long-term facts.
```

Related notes:

- [Project Page](docs/index.html)
- [Install Guide](docs/install.md)
- [Use Cases](docs/use-cases.md)
- [Example Screenshots](docs/example-screenshots.md)
- [GitHub Pages Deploy](docs/github-pages.md)
- [OpenAI Agents SDK compatibility](docs/openai-sdk-compatibility.md)
- [Ollama Gemma check](docs/ollama-gemma-check.md)
- [Voice agents](docs/voice-agents.md)
