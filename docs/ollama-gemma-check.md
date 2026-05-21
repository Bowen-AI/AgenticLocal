# Ollama Gemma Check

Status: tested
Date: 2026-05-20

## Result

Ollama is installed and running on this machine.

Tested models:

```text
gemma3:270m
gemma4:e4b
```

Gemma through Ollama works for plain chat through this runtime:

```bash
python3 -m agentic_loop --provider ollama --model gemma3:270m \
  "Reply with exactly: OK"
```

Result:

```text
OK
```

The adapter command output also includes a note when tool schemas had to be
disabled for this model.

But `gemma3:270m` does not support native Ollama tool calling. Ollama returned:

```text
registry.ollama.ai/library/gemma3:270m does not support tools
```

The adapter now detects that and falls back to a no-tool model call instead of
crashing.

On 2026-05-21, `gemma4:e4b` was tested with native tool calling:

```bash
python3 -m agentic_loop chat \
  --provider ollama \
  --model gemma4:e4b \
  --enable-network-tools
```

The prompt `well, now tell me the news today top news` returned Google News RSS
results through `search_news`.

`ollama ps` reported:

```text
gemma4:e4b    11 GB    100% GPU    32768 context
```

That confirms GPU offload for the loaded model. It does not prove that every GPU
device is active; use host GPU tooling such as `nvidia-smi` for per-device
utilization when the driver is visible to the shell.

The runtime also has a repeated-tool-call guard: if a tool-capable model repeats
the exact same successful tool call, the controller finalizes from the previous
tool result instead of running until the max-step limit.

## Meaning

Gemma can be used as a local chat model in this runtime.

Gemma 3 270M cannot currently be used as the native tool-calling planner for
agentic actions in Ollama. For native Ollama tool calling, use a tool-capable
model such as `gemma4:e4b` or another Ollama model that advertises tool support.

## Check Command

```bash
python3 scripts/smoke_ollama.py --model gemma3:270m
```

Observed smoke result:

```json
{
  "model": "gemma3:270m",
  "native_tool_calling_for_inspect": false,
  "ollama_chat_works": true
}
```
