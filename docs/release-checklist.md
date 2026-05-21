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
- CLI version.
- Package metadata.
- Version consistency between `pyproject.toml` and `agentic_loop.__version__`.

## Current Status

Release check:

```text
PASS
```

Test coverage includes:

- Agent loop/controller behavior.
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
- SQLite workflow event and registry persistence.
- SSE event formatting.
- Max-step stop condition.
- Trace logging.
- CLI smoke path.
- Interactive chat smoke path.
- Server app session behavior.
- Embedded voice page rendering.
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

## Public Release Note

No license has been selected in this repository. It is ready for private/internal
use as version 0.1.0. Select and add a license before public distribution.
