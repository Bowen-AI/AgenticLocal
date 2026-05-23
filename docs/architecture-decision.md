---
layout: default
title: Architecture Decision
description: Why AgenticLocal uses an inspectable local agent loop with a tool registry, policy engine, SQLite storage, and provider adapters instead of a full SDK dependency.
---

# Architecture Decision

Status: current recommendation
Date: 2026-05-20

## Question

Should this project use OpenAI's agent framework directly, or build a local
backend shaped like this?

```text
Backend
  - model client
  - agent loop
  - tool registry
  - memory DB
  - file workspace
  - web/search tool
  - Python execution tool
  - safety/permission layer

Frontend
  - chat UI
  - tool call timeline
  - file browser
  - saved rules/tools
  - project memory view
```

## Finding

OpenAI does provide a real agent framework direction now:

- Agents SDK docs include agent definitions, running agents, orchestration,
  guardrails, results/state, integrations/observability, and evals.
- Function calling/tool calling lets models request application-defined tools
  using schemas.
- The tools docs cover built-in tools, function calling, tool search, and
  remote MCP servers.
- Conversation state docs describe manual state handling, stateful Responses
  API patterns, Conversations API, and `previous_response_id`.

That means OpenAI is a good choice if the priority is:

```text
hosted model quality
official SDK patterns
tracing/evals/guardrails
fastest path to a strong agent brain
```

But OpenAI's framework does not replace the product backend. This project still
needs:

```text
local file workspace
project memory view
tool call timeline
domain-specific tools
permission boundaries
frontend routes/components
optional local model support through Ollama or LocalAI
optional voice interaction layer
```

## Recommendation

Use this local backend shape as the product spine:

```text
chat/session service
-> model selection interface
-> model adapter
-> agent loop
-> policy
-> tools
-> memory
-> traces/evals
```

Then add model adapters:

```text
OpenAI adapter       # best hosted model/Agents SDK path
Ollama adapter       # local-first path
Gemini/OpenAI-compatible adapter # hosted compatible API path
LocalAI adapter      # OpenAI-compatible local server path
Voice adapter        # audio in/out around the same text agent loop
```

This keeps the product independent from any one model provider while still
letting us use OpenAI's agent framework where it helps.

The service may start with a default provider, but it must not lock the whole
server to one model. Clients can select provider/model per `/run`, per `/chat`,
or per session through `/models/select`; UI can discover choices from
`GET /registry/models`.

Runtime model selection is intentionally an interface contract, not a UI
decision. Requests can send:

```json
{
  "model": {
    "provider": "ollama",
    "name": "your-local-model",
    "api_base": null,
    "api_key": null
  }
}
```

At the model-selection interface level, external/local providers validate that
a model name is present. The interactive chat and served CLI entrypoints add a
friendly default, `ollama` with `qwen3.5:4b-mlx`, so first-run users can start
chatting after the installer pulls the default model. The dependency-free
`rule` provider remains available for deterministic tests and offline demos.

Important caveat: not every local Ollama model supports native tool calling.
For example, `gemma3:270m` works as a chat model here, but Ollama rejects tool
schemas for it. Use a tool-capable Ollama model for native agentic tool calls.

For voice, start with a chained pipeline around the existing text session:

```text
speech-to-text -> agentic_loop session -> text-to-speech
```

That pipeline is now implemented in the browser voice page at `/voice`.

Use OpenAI's realtime voice path later if the product needs deeper realtime
audio controls, barge-in, and lower-latency turn taking.

## Current Implementation

This repo now implements the generic local spine:

```text
agentic-loop chat     # interactive terminal chat
agentic-loop serve    # local HTTP service
GET /voice            # embedded browser voice mode
POST /chat            # stateful session chat
POST /run             # one-shot run
POST /models/select   # session model/provider selection
GET /tools            # tool schemas
GET /registry/models  # model/provider registry
GET /health           # service health
```

The Linux/macOS installer supports both checkout installs and a downloaded
bootstrap script:

```bash
curl -fsSL https://raw.githubusercontent.com/Bowen-AI/AgenticLocal/main/scripts/install.sh \
  | bash -s -- --with-ollama
```

That path installs the Python runtime, can install Ollama when missing, and
pulls the default `qwen3.5:4b-mlx` model unless `--no-model-pull` is passed.

The current model is deterministic for testing. That is intentional: it proves
the runtime, policy, session, tools, memory, trace, and server behavior without
requiring an API key or a local model process.

Current storage and policy behavior:

```text
SQLite .agentic/agentic.db
  -> durable sessions/messages
  -> long-term memory
  -> run steps
  -> workflow events/traces
  -> tool registry metadata
  -> UI registry metadata
  -> rule registry metadata and rule settings
  -> workflow registry metadata
  -> optional future model profile registry

Workspace policy
  -> configured read roots
  -> configured write roots
  -> approval-required roots
  -> symlink/path escape checks
```

The default write root is still `outputs/`, but callers can add named writable
roots with `--write-root`, for example `drafts` or `notebooks`.

Next model work should be adapter-focused, not a rewrite:

```text
agentic_loop/providers/openai_compatible.py
agentic_loop/providers/localai.py
agentic_loop/ollama_model.py
agentic_loop/model_selection.py
```

## Sources

- OpenAI Agents SDK docs:
  https://developers.openai.com/api/docs/guides/agents
- OpenAI Agents SDK running agents:
  https://developers.openai.com/api/docs/guides/agents/running-agents
- OpenAI Agents SDK guardrails and human review:
  https://developers.openai.com/api/docs/guides/agents/guardrails-approvals
- OpenAI function calling docs:
  https://developers.openai.com/api/docs/guides/function-calling
- OpenAI tools docs:
  https://developers.openai.com/api/docs/guides/tools
- OpenAI conversation state docs:
  https://developers.openai.com/api/docs/guides/conversation-state
- OpenAI Voice Agents docs:
  https://developers.openai.com/api/docs/guides/voice-agents
