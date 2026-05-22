---
layout: default
title: Agentic AI Loop
description: A concise design note explaining the core agentic AI loop of model, state, tools, and policy that powers AgenticLocal.
---

# Agentic AI: The Loop

Status: draft
Date: 2026-05-20

## Short Version

Agentic AI is not mainly memory.

The core idea is:

```text
agent = model + state + tools + policy loop
```

A chatbot usually does this:

```text
user message -> model -> answer
```

An agent does this:

```text
user goal
-> model decides next step
-> maybe calls a tool
-> runtime executes the tool
-> model observes the result
-> state/context updates
-> model decides again
-> repeat until done
-> final answer or action
```

That repeating loop is the important part.

## What This Repo Implements

This repo implements the design as a small Python runtime:

```text
agentic_loop/
  controller.py  # loop/controller
  model.py       # model interface plus test/demo models
  model_selection.py # provider/model selection contract
  ollama_model.py # Ollama chat adapter
  providers/     # OpenAI-compatible and LocalAI adapters
  tools.py       # tool schemas and real tool functions
  policy.py      # permissions and safety checks
  context.py     # what gets sent to the model each turn
  memory.py      # JSONL memory
  state.py       # current task state
  evals.py       # completion/safety checks
  logs.py        # trace logging
  cli.py         # command-line runner
  chat.py        # interactive terminal chat
  server.py      # local HTTP service
  voice.py       # embedded browser voice page
  session.py     # multi-turn session wrapper
  factory.py     # controller construction
```

The default demo uses `RuleBasedModel`, a deterministic planner that behaves
like a tiny model for testing. That keeps the runtime testable without an API
key. The repo also includes Ollama, OpenAI-compatible, Gemini-compatible, and
LocalAI adapter paths. The controller depends on the `AgentModel` interface, so
model providers can be swapped without rewriting the loop.

Run it:

```bash
python3 -m agentic_loop "Inspect data/sample.csv as a dataset."
```

Install it from Linux or macOS with the bootstrap script:

```bash
curl -fsSL https://raw.githubusercontent.com/Bowen-AI/AgenticLocal/main/scripts/install.sh \
  | bash -s -- --with-ollama
```

The installer can install Ollama and pulls the default `qwen3.5:9b` model when
Ollama is available. Use `--no-model-pull` or `--no-ollama` for narrower
installs.

Run it as an interactive chat:

```bash
python3 -m agentic_loop chat
```

This starts with Ollama `qwen3.5:9b` by default. Switch models inside chat with:

```text
/models
/model ollama qwen3.5:9b
```

Use `--provider rule` for deterministic offline tests and demos.

Run it as a local HTTP service:

```bash
python3 -m agentic_loop serve --host 127.0.0.1 --port 8765
```

The service defaults to Ollama with `qwen3.5:9b` and enables public web/news/fetch
tools. It does not lock the process to one model: clients can discover provider
requirements and choose model settings per request or per session. Start with
`--disable-network-tools` when the HTTP API should run without public network
tools.

```bash
curl -s http://127.0.0.1:8765/registry/models
curl -s -X POST http://127.0.0.1:8765/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"hello","model":{"provider":"ollama","name":"your-local-model"}}'
```

Then use voice mode in a browser:

```text
http://127.0.0.1:8765/voice
```

Run it with Ollama after pulling a model:

```bash
ollama pull your-local-model
python3 -m agentic_loop --provider ollama --model your-local-model \
  "Reply with exactly: OK"
```

Note: Ollama itself does not require this project to pre-pick a model. The
runtime exposes provider/model selection through CLI and HTTP; `qwen3.5:9b` is
only the friendly chat/serve default. Use a model that advertises native tool
calling when you want the model itself to request tools.

Test it:

```bash
python3 -m unittest discover -s tests -v
```

## Why This Matters

It is tempting to describe agents as:

```text
JSON instructions + model + tools + memory
```

That is close, but it misses the thing that makes the system agentic: the
runtime repeatedly asks the model what should happen next, executes approved
actions, feeds the result back, and checks whether the goal is complete.

The model does not directly do work. The model chooses actions. The surrounding
software runs those actions safely.

## The Basic Agent Loop

In pseudocode:

```python
messages = [
    {"role": "system", "content": "You are a helpful agent."},
    {"role": "user", "content": "Find bugs in this repo and fix them."},
]

for step in range(max_steps):
    response = call_model(messages, tools=available_tools)

    if response.final_answer:
        return response.final_answer

    if response.tool_call:
        if not policy_allows(response.tool_call):
            messages.append({
                "role": "system",
                "content": "That tool call was denied by policy."
            })
            continue

        if same_tool_and_arguments_already_succeeded(response.tool_call):
            return final_answer_from_previous_tool_result(response.tool_call)

        result = run_tool(
            response.tool_call.name,
            response.tool_call.arguments,
        )

        messages.append(response.tool_call_message)
        messages.append({
            "role": "tool",
            "tool_call_id": response.tool_call.id,
            "content": result,
        })

return "Stopped because the step limit was reached."
```

This is the skeleton. Production agents add better state, permissions, logging,
human approvals, repeated-call loop guards, retries, and evaluations.

## What The JSON Is For

JSON usually describes tool schemas.

Example:

```json
{
  "name": "read_file",
  "description": "Read a file from the project repository.",
  "parameters": {
    "type": "object",
    "properties": {
      "path": {
        "type": "string",
        "description": "Path to the file"
      }
    },
    "required": ["path"]
  }
}
```

This tells the model:

```text
You may ask to call a tool named read_file.
It accepts one argument named path.
```

The model might produce:

```json
{
  "tool": "read_file",
  "arguments": {
    "path": "src/main.py"
  }
}
```

But the model does not execute the function.

The runtime does:

```python
read_file("src/main.py")
```

So the split is:

```text
model: chooses what to do
runtime: checks policy and executes it
tool: performs the real action
```

## Core Components

| Component | Job |
| --- | --- |
| Goal | The user request or task the agent is trying to finish. |
| Model | Chooses the next action or final answer. |
| Controller | Runs the loop and decides when to continue or stop. |
| Tools | Functions the agent can ask to use. |
| Policy | Permission rules around tools, files, network, cost, and approvals. |
| State | Current task data: steps taken, files seen, errors, hypotheses. |
| Context manager | Chooses what information to send to the model each turn. |
| Memory | Optional persisted state across turns or sessions. |
| Evaluator | Checks whether the work is correct, complete, and safe. |
| Logs/traces | Records what happened so the agent can be debugged. |

## Memory Is Only One Kind Of State

Memory helps, but it is not the main thing.

An agent can be agentic with no long-term memory if it can:

```text
inspect -> act -> observe -> update state -> act again
```

For example, a coding agent can:

```text
read files -> inspect error -> edit code -> run tests -> fix failure -> repeat
```

That is agentic even if it forgets everything after the session.

## Types Of Memory

### Short-Term Context

The current prompt window:

```text
system instructions
+ user request
+ recent conversation
+ recent tool results
```

This is what the model can see right now.

### Working Memory

Temporary task state stored by the runtime:

```json
{
  "files_seen": ["main.py", "utils.py"],
  "tests_failed": ["test_checkout"],
  "current_hypothesis": "inventory update has a race condition"
}
```

This may or may not be sent to the model every turn.

### Long-Term Memory

State persisted across sessions:

```json
{
  "project_language": "python",
  "preferred_test_command": "pytest",
  "user_prefers_concise_summaries": true
}
```

Long-term memory should be deliberate. Bad memory fills up with stale facts,
private details, or random noise.

### Retrieval Memory

Searchable external knowledge:

```text
user asks about architecture
-> agent searches docs/codebase
-> relevant chunks are inserted into context
```

For practical agents, retrieval is often more important than personality-style
memory because it lets the agent work over more information than fits in the
model context window.

## Context Management

The model only sees what the runtime sends.

A good context manager includes:

```text
system instructions
+ user goal
+ compact current state
+ relevant retrieved docs
+ recent messages
+ important tool results
```

A bad context manager dumps everything into the prompt.

A better rule:

```text
Keep the goal.
Keep recent steps.
Retrieve only relevant documents.
Summarize old steps.
Store structured state outside the model.
```

Example:

```python
context = build_context(
    system_prompt=SYSTEM,
    user_goal=goal,
    recent_messages=last_n_messages,
    retrieved_docs=search_memory(goal),
    working_state=summarize_state(state),
)
```

## Tools Make Agents Useful

Tools can be simple or powerful:

```text
read_file
write_file
run_tests
search_web
query_database
send_email
create_calendar_event
call_api
make_plot
deploy_code
```

The controller exposes only approved tools:

```python
TOOLS = {
    "read_file": read_file,
    "write_file": write_file,
    "run_tests": run_tests,
}
```

Then the model selects a tool, and the runtime executes it:

```python
tool_call = model_response.tool_call
result = TOOLS[tool_call.name](**tool_call.arguments)
```

This is why agent building is only partly prompt engineering. Most of the real
work is software engineering around the model.

## Policy And Safety

The policy layer decides what is allowed.

For a coding agent:

```text
Allowed:
- read files in the repo
- edit local files
- run tests
- summarize diffs

Requires approval:
- delete files
- install dependencies
- push to GitHub
- deploy
- access secrets

Denied:
- read unrelated home-directory files
- exfiltrate private data
- run arbitrary network calls
```

The model can ask for an action. The policy decides whether the runtime will do
it.

That distinction matters. Prompt instructions alone are not a security system.

## Stopping And Evaluation

An agent needs to know when to stop.

Common stop conditions:

```text
model returns final answer
max steps reached
budget reached
tool error cannot be repaired
human approval required
evaluator says task is complete
```

Good agents verify their work.

For example:

```text
coding agent -> run tests
data agent -> validate output schema
report agent -> check required sections
biomech agent -> confirm plot file exists and columns match request
```

## Minimal Architecture

Start with this:

```text
agent/
  main.py       # loop/controller
  model.py      # model API calls
  tools.py      # tool definitions and implementations
  state.py      # working state
  memory.py     # optional long-term/retrieval memory
  context.py    # context selection and summarization
  policy.py     # permissions and approvals
  evals.py      # completion and quality checks
  logs.py       # traces/debug records
```

Small version:

```python
def run_agent(user_goal):
    state = {"goal": user_goal, "steps": []}
    messages = make_initial_messages(user_goal)

    for _ in range(8):
        response = call_model(messages, tools=TOOLS)

        if response.final_answer:
            return response.final_answer

        call = response.tool_call

        if not allowed(call.name, call.arguments):
            messages.append({"role": "system", "content": "Tool call denied."})
            continue

        result = TOOLS[call.name](**call.arguments)

        state["steps"].append({
            "tool": call.name,
            "args": call.arguments,
            "result_summary": summarize_result(result),
        })

        messages.append({
            "role": "tool",
            "name": call.name,
            "content": serialize_for_model(result),
        })

    return "Agent stopped after too many steps."
```

## Applying This To BiomechStudio

BiomechStudio does not need a mystical agent. It needs a controlled scientific
workflow agent.

Example user goal:

```text
Clean this IMU dataset and plot knee moment distribution.
```

Possible loop:

```text
1. Inspect uploaded files.
2. Detect columns, units, signals, and sampling rate.
3. Ask whether the suggested preprocessing plan is acceptable.
4. Call approved preprocessing tools.
5. Generate plots and tables.
6. Validate generated artifacts.
7. Save the workflow as a reusable recipe.
8. Summarize results and limitations.
```

Initial tools:

```text
inspect_dataset
summarize_missingness
resample_signal
filter_signal
detect_events
plot_signal
save_project_note
generate_report
```

Policy:

```text
Allowed:
- read inside the project workspace
- write derived files under outputs/
- call approved analysis functions
- generate plots and reports

Denied:
- overwrite raw data
- read outside the workspace
- delete project data
- run arbitrary shell commands
- install packages automatically
- make uncontrolled network calls
```

Good memory for BiomechStudio:

```json
{
  "preferred_filter": "Butterworth low-pass",
  "default_cutoff_hz": 6,
  "preferred_plot_style": "paper-ready",
  "dataset_schema": {
    "imu_columns": ["acc_x", "acc_y", "acc_z"],
    "target_columns": ["vgrf", "knee_moment"]
  }
}
```

Bad memory:

```json
{
  "user_clicked_button_at": "3:04pm",
  "temporary_plot_hover_state": "active",
  "random_guess_about_units": "probably meters"
}
```

## MVP Build Order

Build in this order:

1. Hard-code the loop shape with a deterministic model and max step count.
2. Add a provider/model selection interface before treating hosted/local model choices as product state.
3. Add two safe tools: `inspect_dataset` and `plot_signal`.
4. Add policy checks around file access and output paths.
5. Add structured working state.
6. Add logs/traces for every model turn and tool call.
7. Add simple evals: artifact exists, schema valid, no raw data modified.
8. Add retrieval over project docs/data summaries.
9. Add long-term memory only after the state model is clear.

Do not start with memory. Start with the loop.

## Design Principles

Use these as guardrails:

```text
Tools should be narrow.
Tool results should be structured.
The model should not get raw power by default.
Policy should be enforced in code.
The context should be intentionally built.
Memory should be explicit and reviewable.
Every important action should be logged.
The agent should verify outputs before claiming success.
```

## Bottom Line

Agentic AI is:

```text
LLM + tools + loop + state + context management + policy + evaluation
```

Memory is useful, but memory is not the engine.

The engine is the loop:

```text
decide -> act -> observe -> update -> decide again
```

## Sources

- OpenAI API docs, Agents SDK overview/navigation:
  https://developers.openai.com/api/docs/guides/agents
- OpenAI API docs, running agents:
  https://developers.openai.com/api/docs/guides/agents/running-agents
- OpenAI API docs, guardrails and human review:
  https://developers.openai.com/api/docs/guides/agents/guardrails-approvals
- OpenAI API docs, function calling:
  https://developers.openai.com/api/docs/guides/function-calling
- OpenAI API docs, using tools:
  https://developers.openai.com/api/docs/guides/tools
- OpenAI API docs, conversation state:
  https://developers.openai.com/api/docs/guides/conversation-state
- OpenAI API docs, safety best practices:
  https://developers.openai.com/api/docs/guides/safety-best-practices
