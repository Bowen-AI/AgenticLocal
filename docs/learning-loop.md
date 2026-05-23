---
layout: default
title: Learning Loop
description: Local Hermes-style observe, reflect, distill, approve, reuse, and refine loop for AgenticLocal.
---

# Lightweight Learning Loop

AgenticLocal includes a local Hermes-style learning loop:

```text
observe -> reflect -> distill -> approve -> reuse -> refine
```

The first version is conservative by design. It stores completed-run
experiences in SQLite, proposes draft memories or procedural skills, and waits
for explicit user approval before reusing them. It does not fine-tune a model,
call a vector database, or auto-activate generated skills.

## Modes

Learning is on in draft mode by default:

```bash
python3 -m agentic_loop chat --learning draft
python3 -m agentic_loop serve --learning draft
```

`--learning auto` is accepted for forward compatibility, but in this MVP it
keeps generated skills in draft status to preserve the approval boundary.

Disable it for a run or service:

```bash
python3 -m agentic_loop --learning off "Inspect data/sample.csv"
python3 -m agentic_loop serve --learning off
```

The procedural-skill threshold defaults to `2`, meaning a similar successful
tool pattern must recur twice before the runtime proposes a skill draft. Lower
it for local experiments:

```bash
python3 -m agentic_loop chat --learning-threshold 1
```

## Review Commands

Inside `agentic-loop chat`:

```text
/learn
/learn approve ID
/learn reject ID
/skills
/skill KEY
/skill archive KEY
```

Approving a memory draft writes it to long-term memory with source `learning`.
Approving a skill draft promotes it to an active local Markdown skill. Archiving
a skill disables future reuse without deleting history.

## HTTP API

Served mode exposes the same review surface:

```text
GET  /learning/drafts
POST /learning/drafts/approve
POST /learning/drafts/reject
GET  /skills
GET  /skills/{key}
POST /skills/archive
```

Approval and rejection requests accept `id` or `draft_id`. Skill archive
requests accept `key` or `skill`.

## Storage

The SQLite database stores:

- `experiences`: one sanitized summary per completed run.
- `learning_drafts`: proposed memory, skill, or anti-pattern artifacts.
- `skills`: active or archived procedural skills.
- `skill_uses`: when matched skills were injected and how the run ended.

Events such as `experience_recorded`, `learning_draft_created`,
`skill_approved`, and `skill_used` flow through the existing event timeline and
SSE endpoint.

## Skill Format

Skills are plain Markdown with small front matter:

```markdown
---
key: release-checklist
title: Release Checklist
description: How to prepare an AgenticLocal release safely.
triggers:
  - release
  - changelog
  - push
status: active
---

## When To Use
...

## Procedure
...

## Pitfalls
...

## Verification
...
```

Only compact metadata is considered by default. Full Markdown is injected into
the model context only when lexical trigger matching finds a relevant active
skill for the current goal.

## Safety

- Secrets, API keys, temporary credentials, and full command output are not
  stored by default.
- Generated skills stay in draft status until approval.
- Learning failures are non-blocking and emit `learning_error` events instead
  of failing the user task.
- Vector memory is intentionally deferred; the MVP uses lightweight lexical
  matching so it remains dependency-free and easy to inspect.
