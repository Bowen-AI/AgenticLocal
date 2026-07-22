import json
import urllib.error
import urllib.request
from typing import Any

from .types import Message, ModelResponse, ToolCall


class OllamaError(RuntimeError):
    pass


class ToolsUnsupportedError(OllamaError):
    """Raised when the selected model cannot use tools and silent degrade is off."""


class OllamaChatModel:
    def __init__(
        self,
        model: str,
        host: str = "http://127.0.0.1:11434",
        timeout_s: float = 120.0,
        use_tools: bool = True,
        think: bool | str | None = False,
        # When tools are required, refuse to silently retry without them.
        require_tools: bool = True,
    ):
        self.model = model
        self.host = host.rstrip("/")
        self.timeout_s = timeout_s
        self.use_tools = use_tools
        self.think = think
        self.require_tools = require_tools

    def respond(
        self,
        messages: list[Message],
        tools: list[dict],
        state_summary: str,
    ) -> ModelResponse:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": self._messages(messages),
            "stream": False,
        }
        if self.think is not None:
            payload["think"] = self.think
        if self.use_tools and tools:
            payload["tools"] = [self._tool_schema(tool) for tool in tools]

        data = self._post("/api/chat", payload)
        if data.get("_retried_without_tools"):
            msg = (
                f"Model {self.model!r} does not support native tool calling. "
                "Pick a tool-capable Ollama model (e.g. qwen3, llama3.1, mistral) "
                "or the agent cannot use tools."
            )
            if self.require_tools and tools:
                raise ToolsUnsupportedError(msg)
            return ModelResponse.final(msg, tools_unsupported=True)

        message = data.get("message") or {}
        tool_calls = message.get("tool_calls") or []
        if tool_calls:
            parsed: list[ToolCall] = []
            for i, call in enumerate(tool_calls):
                function = call.get("function") or {}
                name = function.get("name")
                if not name:
                    continue
                parsed.append(
                    ToolCall(
                        name=name,
                        arguments=self._arguments(function.get("arguments", {})),
                        id=call.get("id") or f"ollama_{name}_{i}",
                    )
                )
            if not parsed:
                return ModelResponse.final("Ollama returned tool calls without function names.")
            return ModelResponse.calls(parsed)

        content = message.get("content") or data.get("response") or ""
        return ModelResponse.final(content.strip() or "Ollama returned an empty response.")

    def _messages(self, messages: list[Message]) -> list[dict[str, Any]]:
        rendered = []
        for message in messages:
            if message.role == "tool":
                rendered.append(
                    {
                        "role": "tool",
                        "tool_name": message.name or "tool",
                        "content": message.content,
                    }
                )
            else:
                rendered.append(
                    {
                        "role": message.role,
                        "content": message.content,
                    }
                )
        return rendered

    def _tool_schema(self, tool: dict[str, Any]) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool.get("description", ""),
                "parameters": tool.get("parameters", {"type": "object"}),
            },
        }

    def _arguments(self, value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                return {}
            return parsed if isinstance(parsed, dict) else {}
        return {}

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            f"{self.host}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            if payload.get("tools") and "does not support tools" in body:
                retry_payload = dict(payload)
                retry_payload.pop("tools", None)
                data = self._post(path, retry_payload)
                data["_retried_without_tools"] = True
                return data
            raise OllamaError(f"Ollama HTTP {exc.code}: {body}") from exc
        except urllib.error.URLError as exc:
            raise OllamaError(f"Could not reach Ollama at {self.host}: {exc.reason}") from exc
