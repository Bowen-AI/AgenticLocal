# Changelog

## 0.1.0 - 2026-05-20

Initial release candidate.

Included:

- Minimal dependency-free agent loop runtime.
- Model abstraction with deterministic local planner and scripted model.
- Tool registry with file, CSV, memory, and output-writing tools.
- Workspace policy enforcing read/write boundaries.
- JSONL memory and trace logging.
- CLI runner.
- Interactive terminal chat.
- Local HTTP service with session-aware `/chat` and one-shot `/run`.
- Embedded browser voice mode at `/voice`.
- Ollama chat adapter with graceful fallback for models that do not support
  native tool calling.
- Sample workspace.
- Unit test suite.
- End-to-end smoke test.
- Optional Ollama and HTTP server smoke checks.
- Voice-agent implementation and architecture note.
- Release check script.
