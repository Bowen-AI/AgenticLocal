---
layout: default
title: Release Checklist
---

# Release Checklist

Version: 0.1.0
Date: 2026-05-20

## Commands

Run before release:

```bash
scripts/check_release.sh
```

This checks:

- Python syntax compilation.
- Unit tests.
- End-to-end CLI smoke test.
- Rule/workflow CLI and registry behavior through the unit/smoke suite.
- Runtime model/provider selection registry and validation.
- Universal wheel and source tarball creation.
- Wheel install smoke test when `python3 -m venv` is available.
- CLI version.
- Package metadata.
- Version consistency between `pyproject.toml` and `agentic_loop.__version__`.

CI runs the release check on Linux and macOS with Python 3.11 and 3.12.

## Current Status

Release check:

```text
PASS
```

Test coverage includes:

- Agent loop/controller behavior.
- Repeated identical tool-call loop guard.
- Tool calls.
- Opt-in network tools for web search, news search, and URL fetch.
- CSV inspection.
- Workspace read policy.
- Workspace write policy.
- Symlink escape denial.
- Configurable write roots.
- Approval-required write roots.
- JSONL memory remember/recall.
- SQLite memory remember/recall.
- Durable SQLite server sessions.
- SQLite workflow event and tool/UI/rule/workflow registry persistence.
- Rule context injection and safe write approval behavior.
- Workflow presets, including `/search` requiring network tools and `/release`
  enabling release-readiness framing.
- Model/provider registry and per-request served model selection.
- SSE event formatting.
- Max-step stop condition.
- Trace logging.
- CLI smoke path.
- Interactive chat smoke path.
- Server app session behavior.
- Embedded voice page rendering.
- Embedded rule/workflow controls on the voice page.
- Ollama adapter tool-call parsing.
- Ollama adapter fallback for models that do not support native tools.

Optional environment-dependent checks:

```bash
python3 scripts/smoke_server.py
python3 scripts/smoke_ollama.py --model gemma3:270m
python3 scripts/showcase_e2e.py
```

Some sandboxes block loopback socket binding. In that case, the normal release
check still validates the server application logic without binding a port. The
showcase script also binds a loopback server for HTTP and SSE demos.

The Ollama check requires Ollama to be running and the requested model to be
installed.

Voice support is implemented as an embedded browser page at `/voice`. It uses
browser speech recognition/synthesis and the existing `/chat` endpoint. A
provider-neutral `VoiceAdapter` interface exists for later Gemini Live Voice or
OpenAI Realtime integrations.

## Packaging

Build artifacts locally:

```bash
scripts/package_release.sh
scripts/test_package_install.sh
```

The package builder emits `dist/agentic_loop-*-py3-none-any.whl` and
`dist/agentic-loop-*.tar.gz` using only the Python standard library. The wheel
is platform-independent for Linux and macOS.

Ollama remains an optional system dependency, not a bundled Python dependency.
Use `scripts/install.sh --with-ollama` for a smooth local-model install path
that pulls the default model, or `scripts/install.sh --no-ollama` for API-only
or deterministic rule-mode installs. The same script can be downloaded from
GitHub and run with `bash -s --` flags for Miniconda-style bootstrap installs.

## Public Release Note

No license has been selected in this repository. It is ready for private/internal
use as version 0.1.0. Select and add a license before public distribution.
