# Install Guide

AgenticLocal is dependency-free Python. You can run it directly from the repo,
or install the `agentic-loop` command in editable mode while developing.

## Requirements

- Python 3.11 or newer.
- A local checkout of this repository.
- Optional: Ollama for local model runs.
- Optional: network access when using `--enable-network-tools`.

## Run From Source

From the repository root:

```bash
python3 -m agentic_loop --version
python3 -m agentic_loop "List files in the workspace."
```

Start continuous terminal chat:

```bash
python3 -m agentic_loop chat
```

Start the HTTP service:

```bash
python3 -m agentic_loop serve --host 127.0.0.1 --port 8765
```

Open voice mode:

```text
http://127.0.0.1:8765/voice
```

## Editable Install

When `pip` is available:

```bash
python3 -m pip install -e .
agentic-loop --version
agentic-loop "Inspect data/sample.csv as a dataset."
```

The installed command exposes the same subcommands:

```bash
agentic-loop chat
agentic-loop serve --host 127.0.0.1 --port 8765
```

## Durable State

By default, app state is stored in:

```text
.agentic/agentic.db
```

That SQLite database stores sessions, messages, run steps, long-term memory,
tool/UI registry metadata, and events/traces. It is ignored by git.

Use a different database path:

```bash
python3 -m agentic_loop --db /tmp/agentic-demo.db "Remember project language is python."
python3 -m agentic_loop --db /tmp/agentic-demo.db "What is the project language?"
```

## Workspace Permissions

The default workspace is `sample_workspace`. The default writable root is
`outputs/`.

Write to the default root:

```bash
python3 -m agentic_loop "Write a note saying hello from the agent."
```

Add named write roots:

```bash
python3 -m agentic_loop \
  --write-root drafts \
  "Save a draft note."
```

Mark a write root as approval-required:

```bash
python3 -m agentic_loop \
  --write-root reviewed \
  --approval-root reviewed \
  "Write a reviewed note."
```

## Network Tools

Network tools are opt-in. They add `search_web`, `search_news`, and `fetch_url`.

```bash
python3 -m agentic_loop chat --enable-network-tools
```

Example prompts:

```text
Search the internet for agentic AI.
Search news about robotics.
Fetch https://example.com and summarize it.
```

## Ollama

For local model runs, install Ollama separately and pull a tool-capable model.

```bash
ollama pull gemma4:e4b
python3 -m agentic_loop chat \
  --provider ollama \
  --model gemma4:e4b \
  --enable-network-tools
```

Check what Ollama has loaded:

```bash
ollama ps
```

If a model does not support native tool calling, the adapter falls back to a
plain chat response when possible. Use a model that advertises `tools` support
for agentic tool use.

## HTTP API

Start the service:

```bash
python3 -m agentic_loop serve \
  --host 127.0.0.1 \
  --port 8765 \
  --enable-network-tools
```

Call it:

```bash
curl -s http://127.0.0.1:8765/health
curl -s http://127.0.0.1:8765/tools
curl -s -X POST http://127.0.0.1:8765/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"Inspect data/sample.csv as a dataset."}'
curl -N "http://127.0.0.1:8765/events?follow=1&timeout=30"
```

Useful endpoints:

```text
GET  /health
GET  /tools
GET  /memory
GET  /sessions
GET  /events
GET  /events?follow=1&timeout=30
GET  /registry/tools
GET  /registry/ui
GET  /voice
POST /chat
POST /run
POST /sessions
```

## Verify

Run the normal test suite:

```bash
python3 -m unittest discover -s tests -v
```

Run the release check:

```bash
scripts/check_release.sh
```

Run the showcase:

```bash
python3 scripts/showcase_e2e.py
```

Some sandboxes block loopback sockets or network calls. In that case, the unit
tests still validate the runtime without external services.
