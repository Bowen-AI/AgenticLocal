---
layout: default
title: Use Cases
---

# Use Cases

These use cases describe what AgenticLocal can do now, plus where the current
architecture is meant to grow.

## 1. Local Workspace Assistant

Use the agent to inspect files, read notes, write safe outputs, and summarize
project artifacts inside a configured workspace.

```bash
python3 -m agentic_loop "List files in the workspace."
python3 -m agentic_loop "Read notes/example.txt and summarize it."
python3 -m agentic_loop "Write a note saying hello from the agent."
```

Why it matters:

- File reads stay inside configured read roots.
- Writes default to `outputs/`.
- Extra write roots are explicit through `--write-root`.
- Symlink/path escape attempts are denied.

## 2. Dataset Triage

Inspect CSV data before writing analysis code.

```bash
python3 -m agentic_loop "Inspect data/sample.csv as a dataset."
```

Current behavior:

- Reads CSV headers and rows.
- Counts missing values.
- Detects fully numeric column ranges.
- Emits structured step data when `--json` is used.

## 3. Durable Chat And Memory

Use SQLite-backed sessions and long-term memory across runs.

```bash
python3 -m agentic_loop --db /tmp/agentic.db "Remember project language is python."
python3 -m agentic_loop --db /tmp/agentic.db "What is the project language?"
```

Memory split:

- Short-term context: messages sent to the model for the current turn.
- Working memory: run steps and `AgentState`.
- Session memory: transcript persisted by `session_id`.
- Long-term memory: deliberate `remember`/`recall` facts.
- Retrieval memory: future searchable project/code/docs chunks.

## 4. Research And News Assistant

Opt into public network tools when you want live information.

```bash
python3 -m agentic_loop chat --enable-network-tools
```

Try:

```text
Search news about robotics.
Search the internet for agentic AI.
Fetch https://example.com and summarize it.
```

Current tools:

- `search_web`: DuckDuckGo-backed web search.
- `search_news`: Google News RSS search.
- `fetch_url`: HTTP/HTTPS page fetch and text extraction.

The controller protects against repeated identical successful tool calls. If a
tool-capable model keeps asking for the same already-completed action, the
runtime finalizes from the previous result instead of burning through the step
limit.

## 5. Human-Gated Workspace Changes

Use approval-required roots for outputs that should pause for review.

```bash
python3 -m agentic_loop \
  --write-root reviewed \
  --approval-root reviewed \
  "Write a reviewed note."
```

Current behavior:

- The policy engine marks the write as `approval_required`.
- The file is not written.
- Events/traces record the approval requirement.

Future UI work can turn that event into an approval modal.

## 6. Local HTTP Agent Service

Run the same runtime behind HTTP for local apps and dashboards.

```bash
python3 -m agentic_loop serve \
  --host 127.0.0.1 \
  --port 8765 \
  --enable-network-tools
```

Useful workflows:

- POST `/chat` for stateful conversations.
- POST `/run` for one-shot jobs.
- GET `/events` for event snapshots.
- GET `/events?follow=1&timeout=30` for SSE streaming.
- GET `/registry/ui` to see component mappings.
- GET `/voice` for the browser speech page.

## 7. Tool Timeline And UI Registry

The storage layer persists tool and UI registry metadata.

Examples:

- `inspect_csv` maps to `table_preview`.
- `list_files` maps to `file_browser`.
- `remember` and `recall` map to `memory_view`.
- Network searches map to search/news result components.
- Approval-required events can map to an approval modal.

This lets a frontend render the same runtime events as a timeline, table
preview, file browser, memory view, or modal without hardcoding every tool in
the page.

## 8. Voice Companion Around The Same Runtime

The browser voice page currently uses:

```text
Browser Web Speech API -> POST /chat -> browser speech synthesis
```

The core architecture keeps voice as an adapter boundary, so future realtime
providers can sit around the same policy, tools, memory, and trace system.

Documented provider examples:

- Gemini Live Voice.
- OpenAI Realtime.

## 9. Provider-Swappable Brain

The model interface is provider-neutral.

Current paths:

- `rule`: deterministic local planner for tests and demos.
- `ollama`: local model adapter.
- `openai-compatible`: API-key-backed compatible endpoint.
- `localai`: LocalAI-compatible endpoint.

Example Ollama run:

```bash
python3 -m agentic_loop chat \
  --provider ollama \
  --model gemma4:e4b \
  --enable-network-tools
```

## 10. Research Product Direction

The natural next product shape is a local-first research workspace:

- Search papers and datasets.
- Fetch and snapshot sources.
- Inspect downloaded tables.
- Validate equations and assumptions.
- Keep provenance on every result.
- Stream tool progress into a timeline.
- Let users approve downloads, writes, and trusted-source transitions.

The current runtime already has the main spine for that direction: policy,
tools, events, durable state, registries, and provider adapters.
