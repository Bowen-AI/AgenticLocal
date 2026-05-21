# Ollama Gemma Check

Status: tested
Date: 2026-05-20

## Result

Ollama is installed and running on this machine.

Installed model:

```text
gemma3:270m
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

## Meaning

Gemma can be used as a local chat model in this runtime.

Gemma 3 270M cannot currently be used as the native tool-calling planner for
agentic actions in Ollama. For native Ollama tool calling, use a tool-capable
model. Ollama's own tool-calling docs use `qwen3` in their examples.

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
