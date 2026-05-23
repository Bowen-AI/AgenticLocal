---
layout: default
title: Voice Agents
description: Voice-agent architecture notes for AgenticLocal, including browser voice mode, realtime integration plans, and speech pipeline options.
---

# Voice Agents

Status: browser voice implemented, Gemini Live realtime adapter implemented
Date: 2026-05-23

## Does Realtime Voice Fit This Repo?

Yes. Realtime voice can sit around the existing local agent loop instead of
replacing it. AgenticLocal keeps this split:

```text
microphone/audio transport -> transcript -> POST /chat -> spoken answer
```

The backend still owns sessions, model selection, tool policy, memory, traces,
rules, workflows, and the timeline. Gemini Live handles browser microphone
streaming and speech playback when credentials are configured.

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

For Gemini Live, set an API key before starting the server:

```bash
export GEMINI_API_KEY="..."
python3 -m agentic_loop serve --voice-provider auto
```

`GOOGLE_API_KEY` is also accepted. The server never sends that long-lived key
to the browser. It mints short-lived Gemini Live ephemeral tokens at:

```text
POST /voice/gemini/token
```

The browser uses those tokens to connect to Gemini Live's constrained WebSocket
endpoint. The local server also exposes:

```text
GET /voice/config
```

for UI availability and fallback state.

The live path is:

```text
Gemini Live input transcription
-> existing agentic_loop session through POST /chat
-> Gemini Live audio playback
```

The fallback path is:

```text
SpeechRecognition -> POST /chat -> speechSynthesis
```

Both paths preserve transcript, policy checks, tool calls, memory writes, and
approvals in the normal runtime.

## What Is Implemented

Implemented:

- Browser voice page served by the local backend.
- Gemini Live voice mode when `GEMINI_API_KEY` or `GOOGLE_API_KEY` is set.
- `GET /voice/config` for live/fallback availability.
- `POST /voice/gemini/token` for one-use ephemeral Live tokens.
- `--voice-provider auto|browser|gemini-live`.
- `--voice-model MODEL`, defaulting to
  `AGENTIC_LOOP_GEMINI_LIVE_MODEL` or
  `gemini-2.5-flash-native-audio-preview-12-2025`.
- Microphone speech recognition when the browser supports
  `SpeechRecognition` or `webkitSpeechRecognition`.
- Text fallback input.
- Session-aware `/chat` calls.
- Spoken responses through `speechSynthesis`.
- Tool-call timeline display.

Not implemented:

- OpenAI Realtime speech-to-speech sessions.
- Server-side audio transcription.
- Server-side text-to-speech.
- Backend cancellation of an already-running `AgentSession.ask`.
- Full production hardening for Gemini preview model changes.

## Recommended Next Build Order

1. Exercise Gemini Live manually with real credentials in Chrome.
2. Add backend cancellation for long-running voice turns.
3. Store richer audio/transcription metadata alongside tool traces.
4. Add an OpenAI Realtime adapter using the same voice boundary.
5. Add provider-specific voice/model selectors if multiple live providers are
   enabled.

## When To Use Realtime Speech-To-Speech

Use a realtime provider path when the product needs:

```text
natural turn taking
low first-audio latency
barge-in / interruption
live audio in the browser
```

In this repo, realtime audio still sits beside the current HTTP service instead
of replacing the local agent loop.

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

- Gemini Live API guide:
  https://ai.google.dev/gemini-api/docs/live
- Gemini ephemeral tokens:
  https://ai.google.dev/gemini-api/docs/ephemeral-tokens
- Gemini Live WebSocket reference:
  https://ai.google.dev/api/live
- OpenAI Voice Agents guide:
  https://developers.openai.com/api/docs/guides/voice-agents
- OpenAI Realtime and audio overview:
  https://developers.openai.com/api/docs/guides/realtime
- OpenAI WebRTC guide:
  https://developers.openai.com/api/docs/guides/realtime-webrtc
- OpenAI WebSocket guide:
  https://developers.openai.com/api/docs/guides/realtime-websocket
