---
layout: default
title: Voice Agents
---

# Voice Agents

Status: implemented locally, OpenAI realtime integration planned
Date: 2026-05-20

## Does OpenAI Support Voice Agents?

Yes. OpenAI's Voice Agents guide describes two supported architecture paths:

```text
1. Speech-to-speech live audio session
2. Chained voice pipeline
```

The docs recommend:

- TypeScript `RealtimeAgent` plus `RealtimeSession` for browser-based,
  low-latency voice assistants.
- Python `VoicePipeline` for extending an existing text agent into a voice
  workflow.

## How This Maps To This Repo

This repo supports text interaction:

```text
terminal chat -> agent loop -> tools/policy/memory -> answer
HTTP /chat    -> agent loop -> tools/policy/memory -> answer
```

It also embeds browser voice mode at:

```text
http://127.0.0.1:8765/voice
```

Run:

```bash
python3 -m agentic_loop serve --host 127.0.0.1 --port 8765
```

The `/voice` page uses browser Web Speech APIs:

```text
SpeechRecognition -> POST /chat -> speechSynthesis
```

That means microphone capture and spoken replies happen in the browser, while
the backend still owns the agent loop, tools, policy, memory, and traces.

The implemented voice path is the chained pipeline:

```text
speech-to-text
-> existing agentic_loop session
-> text-to-speech
```

That path fits our design because the transcript, policy checks, tool calls,
memory writes, and approvals remain visible and testable.

## What Is Implemented

Implemented:

- Browser voice page served by the local backend.
- Microphone speech recognition when the browser supports
  `SpeechRecognition` or `webkitSpeechRecognition`.
- Text fallback input.
- Session-aware `/chat` calls.
- Spoken responses through `speechSynthesis`.
- Tool-call timeline display.

Not implemented:

- OpenAI Realtime speech-to-speech sessions.
- Gemini Live Voice sessions.
- Server-side audio transcription.
- Server-side text-to-speech.
- Full barge-in/interruption management beyond browser speech controls.

## Recommended Next Build Order

1. Keep the existing `agentic_loop` text session as the core workflow.
2. Extend the provider-neutral `VoiceAdapter` interface for audio sessions.
3. Store the transcript alongside tool traces in SQLite.
4. Run normal policy/tool checks before generating speech.
5. Add a Gemini Live Voice or OpenAI Realtime implementation when low-latency
   interruption and barge-in become important.

## When To Use Realtime Speech-To-Speech

Use OpenAI's realtime path when the product needs:

```text
natural turn taking
low first-audio latency
barge-in / interruption
live audio in the browser
realtime tool use
```

That would likely sit beside the current HTTP service rather than replace it.

## When To Use A Chained Pipeline

Use a chained pipeline when the product needs:

```text
durable transcripts
explicit policy checks
approval-heavy workflows
debuggable tool calls
reuse of the existing text agent
clear intermediate state
```

That is the better first fit for this repo.

## Sources

- OpenAI Voice Agents guide:
  https://developers.openai.com/api/docs/guides/voice-agents
- OpenAI Realtime and audio overview:
  https://developers.openai.com/api/docs/guides/realtime
- OpenAI WebRTC guide:
  https://developers.openai.com/api/docs/guides/realtime-webrtc
- OpenAI WebSocket guide:
  https://developers.openai.com/api/docs/guides/realtime-websocket
