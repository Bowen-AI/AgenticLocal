# Agentic AI Loop

This repository contains a dependency-free implementation of a minimal agentic
AI runtime:

```text
agent = model + state + tools + policy loop
```

Current version: `0.1.0`

Start here:

- [Agentic AI: The Loop](docs/design/agentic-ai-loop.md)
- [Install Guide](docs/install.md)
- [Use Cases](docs/use-cases.md)
- [Example Screenshots](docs/example-screenshots.md)

## Run The Demo

Start an interactive agent chat:

```bash
python3 -m agentic_loop chat
```

Start interactive chat with opt-in public web/news tools:

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

Expose public web/news tools in the local service:

```bash
python3 -m agentic_loop serve \
  --host 127.0.0.1 \
  --port 8765 \
  --enable-network-tools
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
curl -s -X POST http://127.0.0.1:8765/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"Inspect data/sample.csv as a dataset."}'
```

By default, durable app state is stored in:

```text
.agentic/agentic.db
```

That SQLite database stores sessions, messages, run steps, long-term memory,
events/traces, tool registry metadata, and UI registry metadata. JSONL memory
and trace files are still available as optional legacy/export paths through
`--memory` and `--trace`.

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
- tool/UI registry metadata
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

## Architecture Direction

See [Architecture Decision](docs/architecture-decision.md).

Current architecture:

```text
User / UI
  -> Terminal chat, HTTP chat, browser voice page, tool timeline

HTTP API
  -> POST /chat
  -> POST /run
  -> GET /events        SSE event stream snapshot
  -> GET /events?follow=1&timeout=30
  -> GET /tools         tool schemas + registry metadata
  -> GET /memory        long-term memory records
  -> GET /sessions      durable session list
  -> GET /registry/ui   UI component registry metadata

Agent Runtime
  -> Context Builder
  -> Brain / Model Adapter
       - Rule model
       - Ollama
       - OpenAI-compatible
       - LocalAI
       - other provider API keys through the adapter boundary
  -> Policy / Approval Engine
       - configured read roots
       - configured write roots
       - approval-required roots
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

- [Install Guide](docs/install.md)
- [Use Cases](docs/use-cases.md)
- [Example Screenshots](docs/example-screenshots.md)
- [OpenAI Agents SDK compatibility](docs/openai-sdk-compatibility.md)
- [Ollama Gemma check](docs/ollama-gemma-check.md)
- [Voice agents](docs/voice-agents.md)
