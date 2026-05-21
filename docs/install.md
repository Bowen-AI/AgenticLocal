---
layout: default
title: Install Guide
---

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

## Easy Install On Linux Or macOS

From a local checkout:

```bash
scripts/install.sh
agentic-loop --version
agentic-loop "Inspect data/sample.csv as a dataset."
```

The installer creates an isolated environment under
`~/.local/share/agentic-loop` and writes a launcher to `~/.local/bin`. Add
`~/.local/bin` to `PATH` if your shell does not already include it.

If Python venv/pip support is missing, install it and rerun the script:

```bash
# macOS with Homebrew
brew install python

# Debian/Ubuntu
sudo apt install python3-venv python3-pip
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

## Build Packages

Build a universal wheel and source tarball:

```bash
scripts/package_release.sh
ls dist/
```

The package builder uses only the Python standard library. The wheel is pure
Python and works on Linux and macOS with Python 3.11 or newer.

## Durable State

By default, app state is stored in:

```text
.agentic/agentic.db
```

That SQLite database stores sessions, messages, run steps, long-term memory,
tool/UI registry metadata, rule/workflow registry metadata, and events/traces.
It is ignored by git.

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
The runtime does not require Ollama by default; choose an Ollama model only when
you use `--provider ollama`.

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
curl -s http://127.0.0.1:8765/registry/models
curl -s http://127.0.0.1:8765/registry/rules
curl -s http://127.0.0.1:8765/registry/workflows
curl -s -X POST http://127.0.0.1:8765/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"Inspect data/sample.csv as a dataset.","workflow":"loop"}'
curl -N "http://127.0.0.1:8765/events?follow=1&timeout=30"
```

Select a provider/model per served request:

```bash
curl -s -X POST http://127.0.0.1:8765/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"hello","model":{"provider":"ollama","name":"your-local-model"}}'

curl -s -X POST http://127.0.0.1:8765/models/select \
  -H "Content-Type: application/json" \
  -d '{"model":{"provider":"openai-compatible","name":"your-model","api_base":"https://provider.example/v1","api_key":"..."}}'
```

Model selection payloads use this shape:

```json
{
  "model": {
    "provider": "rule | ollama | openai | openai-compatible | gemini | localai",
    "name": "provider-specific-model-name",
    "ollama_host": "http://127.0.0.1:11434",
    "api_base": "https://provider.example/v1",
    "api_key": "optional-secret"
  }
}
```

`rule` needs no model. `ollama`, `openai`, `openai-compatible`, `gemini`, and
`localai` require an explicit model name. Compatible hosted providers also need
the right `api_base` and, when required by that provider, an API key.

Use the CLI against a running server:

```bash
agentic-loop client --models
agentic-loop client --provider ollama --model your-local-model "hello"
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
GET  /registry/rules
GET  /registry/workflows
GET  /registry/models
GET  /voice
POST /chat
POST /run
POST /sessions
POST /models/select
POST /rules/toggle
POST /workflows/start
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
