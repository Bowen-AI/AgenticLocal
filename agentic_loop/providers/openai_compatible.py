import json
import os
import urllib.error
import urllib.request
from typing import Any

from ..types import Message, ModelResponse, ToolCall


class OpenAICompatibleError(RuntimeError):
    pass


class OpenAICompatibleChatModel:
    """Chat-completions adapter for OpenAI-compatible HTTP providers."""

    def __init__(
        self,
        model: str,
        base_url: str = "https://api.openai.com/v1",
        api_key: str | None = None,
        timeout_s: float = 120.0,
    ):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key if api_key is not None else os.environ.get("OPENAI_API_KEY")
        self.timeout_s = timeout_s

    def respond(
        self,
        messages: list[Message],
        tools: list[dict],
        state_summary: str,
    ) -> ModelResponse:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": self._messages(messages),
        }
        if tools:
            payload["tools"] = [self._tool_schema(tool) for tool in tools]

        data = self._post("/chat/completions", payload)
        choices = data.get("choices") or []
        if not choices:
            return ModelResponse.final("Provider returned no choices.")

        message = choices[0].get("message") or {}
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
                        id=call.get("id") or f"openai_compatible_{name}_{i}",
                    )
                )
            if not parsed:
                return ModelResponse.final("Provider returned tool calls without function names.")
            return ModelResponse.calls(parsed)

        content = message.get("content") or ""
        return ModelResponse.final(content.strip() or "Provider returned an empty response.")

    def _messages(self, messages: list[Message]) -> list[dict[str, Any]]:
        rendered = []
        for message in messages:
            item: dict[str, Any] = {
                "role": message.role,
                "content": message.content,
            }
            if message.role == "tool":
                item["tool_call_id"] = message.tool_call_id or message.name or "tool"
            if message.name:
                item["name"] = message.name
            rendered.append(item)
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
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise OpenAICompatibleError(f"Provider HTTP {exc.code}: {body}") from exc
        except urllib.error.URLError as exc:
            raise OpenAICompatibleError(
                f"Could not reach provider at {self.base_url}: {exc.reason}"
            ) from exc
