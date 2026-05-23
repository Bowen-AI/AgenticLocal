---
layout: default
title: Install Guide
description: Install AgenticLocal from source or with the bootstrap script, run the agentic-loop command, start chat, and configure Ollama or provider adapters.
---

# Install Guide

AgenticLocal is dependency-free Python. You can run it directly from the repo,
or install the `agentic-loop` command in editable mode while developing.

## Requirements

- Python 3.11 or newer.
- A local checkout of this repository.
- Optional: Ollama for local model runs.
- Optional: network access for served web/news/fetch tools, or for chat and
  one-shot runs started with `--enable-network-tools`.

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

Download the installer script:

```bash
curl -fsSL https://raw.githubusercontent.com/Bowen-AI/AgenticLocal/main/scripts/install.sh \
  -o install-agentic-loop.sh
bash install-agentic-loop.sh --with-ollama
agentic-loop --version
agentic-loop "Inspect data/sample.csv as a dataset."
```

Or pipe it directly into Bash:

```bash
curl -fsSL https://raw.githubusercontent.com/Bowen-AI/AgenticLocal/main/scripts/install.sh \
  | bash -s -- --with-ollama
```

From a local checkout:

```bash
scripts/install.sh
agentic-loop --version
agentic-loop "Inspect data/sample.csv as a dataset."
```

The installer creates an isolated environment under
`~/.local/share/agentic-loop` and writes a launcher to `~/.local/bin`. Add
`~/.local/bin` to `PATH` if your shell does not already include it.

Ollama is installed as a system application rather than a Python dependency.
When `ollama` is missing, the installer prompts before running the official
Ollama installer. When Ollama is available, it pulls the default model used by
chat and serve unless you pass `--no-model-pull`:

```bash
# Prompt for Ollama setup.
scripts/install.sh

# Noninteractive local-model setup. This installs Ollama if missing and pulls
# qwen3.5:4b-mlx by default.
scripts/install.sh --with-ollama

# Choose a different model, skip the model pull, or skip Ollama entirely.
scripts/install.sh --ollama-model qwen3.5:4b-mlx
scripts/install.sh --no-model-pull
scripts/install.sh --no-ollama
```

The same behavior can be controlled with `AGENTIC_LOOP_INSTALL_OLLAMA`,
`AGENTIC_LOOP_PULL_MODEL`, `AGENTIC_LOOP_OLLAMA_MODEL`, and
`AGENTIC_LOOP_SOURCE_URL`.

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
learning experiences/drafts/skills, tool/UI registry metadata, rule/workflow
registry metadata, and events/traces.
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
Interactive chat and serve default to Ollama with `qwen3.5:4b-mlx`; use
`--provider rule` when you want the dependency-free deterministic provider.

```bash
ollama pull qwen3.5:4b-mlx
python3 -m agentic_loop chat --enable-network-tools
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
  --port 8765
```

The service enables public web/news/fetch tools by default. Add
`--disable-network-tools` when you want the HTTP API to run without them.

Call it:

```bash
curl -s http://127.0.0.1:8765/health
curl -s http://127.0.0.1:8765/tools
curl -s http://127.0.0.1:8765/registry/models
curl -s http://127.0.0.1:8765/registry/rules
curl -s http://127.0.0.1:8765/registry/workflows
curl -s http://127.0.0.1:8765/learning/drafts
curl -s http://127.0.0.1:8765/skills
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

Inside interactive chat:

```text
/models
/model ollama qwen3.5:4b-mlx
/model openai your-openai-model
/model provider=openai-compatible model=your-model api_base=https://provider.example/v1 api_key=...
/learn
/learn approve ID
/learn reject ID
/skills
/skill KEY
/skill archive KEY
```

If you do not pass `--provider`, interactive chat starts with Ollama `qwen3.5:4b-mlx`.
Use `--provider rule` when you want deterministic local smoke tests and tool
demos without a model server.

Useful endpoints:

```text
GET  /health
GET  /tools
GET  /memory
GET  /learning/drafts
GET  /skills
GET  /skills/{key}
GET  /sessions
GET  /events
GET  /events?follow=1&timeout=30
GET  /registry/tools
GET  /registry/ui
GET  /registry/rules
GET  /registry/workflows
GET  /registry/models
GET  /voice
GET  /voice/config
POST /chat
POST /run
POST /sessions
POST /voice/gemini/token
POST /models/select
POST /learning/drafts/approve
POST /learning/drafts/reject
POST /skills/archive
POST /rules/toggle
POST /workflows/start
```

Learning defaults to `--learning draft`, which records completed-run
experiences and creates draft memories or procedural skills only when the local
threshold is met. Use `--learning off` to disable it, or
`--learning-threshold N` to tune how many repeated successful patterns are
needed before a skill draft appears.

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
