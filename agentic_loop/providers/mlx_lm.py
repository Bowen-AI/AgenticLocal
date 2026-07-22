"""Optional in-process MLX-LM engine for Apple Silicon.

Loads weights via ``mlx_lm`` when installed. Not a full OpenAI-tools
implementation — models that emit tool-call JSON in content are parsed; otherwise
the response is treated as a final answer. Prefer Ollama for production tool use.
"""

from __future__ import annotations

import json
import re
from typing import Any

from ..types import Message, ModelResponse, ToolCall


class MlxLmError(RuntimeError):
    pass


_TOOL_JSON = re.compile(
    r"\{[^{}]*\"name\"\s*:\s*\"([^\"]+)\"[^{}]*\"arguments\"\s*:\s*(\{.*?\})[^{}]*\}",
    re.DOTALL,
)


class MlxLmChatModel:
    def __init__(self, model: str, max_tokens: int = 1024):
        self.model_id = model
        self.max_tokens = max_tokens
        self._model = None
        self._tokenizer = None

    def _ensure_loaded(self):
        if self._model is not None:
            return
        try:
            from mlx_lm import load
        except Exception as exc:  # noqa: BLE001
            raise MlxLmError(
                "mlx_lm is not installed. On Apple Silicon: pip install mlx-lm"
            ) from exc
        self._model, self._tokenizer = load(self.model_id)

    def respond(
        self,
        messages: list[Message],
        tools: list[dict],
        state_summary: str,
    ) -> ModelResponse:
        self._ensure_loaded()
        from mlx_lm import generate

        prompt = self._format_prompt(messages, tools)
        text = generate(
            self._model,
            self._tokenizer,
            prompt=prompt,
            max_tokens=self.max_tokens,
            verbose=False,
        )
        text = (text or "").strip()
        if tools:
            calls = self._parse_tool_calls(text)
            if calls:
                return ModelResponse.calls(calls)
        return ModelResponse.final(text or "MLX-LM returned an empty response.")

    def unload(self) -> None:
        self._model = None
        self._tokenizer = None

    def _format_prompt(self, messages: list[Message], tools: list[dict]) -> str:
        parts = []
        if tools:
            names = ", ".join(t.get("name", "?") for t in tools)
            parts.append(
                "You are a tool-using assistant. When you need a tool, reply with JSON only: "
                '{"name":"<tool>","arguments":{...}}. Available tools: ' + names
            )
        for message in messages:
            parts.append(f"{message.role.upper()}: {message.content}")
        parts.append("ASSISTANT:")
        return "\n".join(parts)

    def _parse_tool_calls(self, text: str) -> list[ToolCall]:
        calls: list[ToolCall] = []
        for i, match in enumerate(_TOOL_JSON.finditer(text)):
            name = match.group(1)
            try:
                args = json.loads(match.group(2))
            except json.JSONDecodeError:
                args = {}
            if isinstance(args, dict):
                calls.append(ToolCall(name=name, arguments=args, id=f"mlx_{name}_{i}"))
        if not calls:
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                return []
            if isinstance(data, dict) and data.get("name"):
                args = data.get("arguments") or data.get("parameters") or {}
                if isinstance(args, dict):
                    calls.append(
                        ToolCall(name=str(data["name"]), arguments=args, id="mlx_0")
                    )
        return calls
