# OpenAI Agents SDK Compatibility

Status: current
Date: 2026-05-20

This project follows the same core agent-loop shape as the OpenAI Agents SDK,
but it is not a drop-in reimplementation of the whole SDK.

## Similarities

Implemented locally:

- Agent loop: model response, tool call, tool result, repeat, final answer.
- Tool schemas.
- Tool execution owned by application code.
- Session-based multi-turn chat.
- Local memory store.
- Policy checks around tools and workspace access.
- Trace logging.
- HTTP `/chat` and `/run` service shape.
- Ollama model adapter for local chat.
- Embedded browser voice page using `/chat`.

This matches the conceptual flow described in OpenAI's running-agents docs:
model call, inspect output, execute tool calls, continue, or return final
answer.

## Not Implemented

This repo does not currently implement all OpenAI Agents SDK methods or
features.

Missing or only represented as local analogues:

- Official `Agent`, `Runner`, and SDK result types.
- OpenAI model adapter.
- OpenAI Conversations API integration.
- `previous_response_id` continuation.
- Streaming agent runs.
- Agent handoffs/orchestration across specialists.
- Hosted OpenAI tools.
- MCP tool registration.
- Human-in-the-loop approval pause/resume.
- OpenAI tracing/evals integration.
- Sandbox agents.
- ChatKit/frontend widgets.
- OpenAI realtime voice agents. A browser voice page exists locally; see
  [Voice Agents](voice-agents.md).

## Recommendation

Use this repo as the provider-neutral backend spine:

```text
chat/session service
-> model adapter
-> agent loop
-> policy
-> tools
-> memory
-> traces/evals
```

Then add an OpenAI Agents SDK adapter if we want the official SDK runtime and
hosted capabilities.
