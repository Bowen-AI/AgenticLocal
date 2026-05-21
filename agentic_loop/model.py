import json
import re
from collections import deque
from typing import Protocol

from .types import Message, ModelResponse


class AgentModel(Protocol):
    def respond(
        self,
        messages: list[Message],
        tools: list[dict],
        state_summary: str,
    ) -> ModelResponse:
        ...


class ScriptedModel:
    def __init__(self, responses: list[ModelResponse]):
        self.responses = deque(responses)

    def respond(
        self,
        messages: list[Message],
        tools: list[dict],
        state_summary: str,
    ) -> ModelResponse:
        if not self.responses:
            return ModelResponse.final("No scripted responses left.")
        return self.responses.popleft()


class RuleBasedModel:
    """A deterministic local planner used to test the agent runtime offline."""

    def respond(
        self,
        messages: list[Message],
        tools: list[dict],
        state_summary: str,
    ) -> ModelResponse:
        goal = self._goal(messages)
        tool_messages = [message for message in messages if message.role == "tool"]
        denied = [message for message in messages if "denied by policy" in message.content]

        if denied:
            return ModelResponse.final(
                "I could not complete that action because the policy layer denied it."
            )

        if self._extract_url(goal) and not self._called(tool_messages, "fetch_url"):
            return ModelResponse.call(
                "fetch_url",
                {"url": self._extract_url(goal), "max_chars": 4000},
                "call_fetch_url",
            )

        if self._mentions(goal, "news", "headline", "headlines", "latest", "current events", "today") and not self._called(tool_messages, "search_news"):
            return ModelResponse.call(
                "search_news",
                {"query": self._search_query(goal), "max_results": 5},
                "call_search_news",
            )

        if self._mentions(goal, "search web", "search the web", "search internet", "search the internet", "web search", "internet search", "look up", "google") and not self._called(tool_messages, "search_web"):
            return ModelResponse.call(
                "search_web",
                {"query": self._search_query(goal), "max_results": 5},
                "call_search_web",
            )

        if self._mentions(goal, "remember") and not self._called(tool_messages, "remember"):
            key, value = self._parse_memory_goal(goal)
            return ModelResponse.call("remember", {"key": key, "value": value}, "call_remember")

        if self._mentions(goal, "recall", "what do you remember", "what is") and not self._called(tool_messages, "recall"):
            return ModelResponse.call("recall", {"query": self._memory_query(goal)}, "call_recall")

        if self._mentions(goal, "inspect", "csv", "dataset") and not self._called(tool_messages, "inspect_csv"):
            return ModelResponse.call("inspect_csv", {"path": self._extract_path(goal, ".csv")}, "call_inspect")

        if self._mentions(goal, "read") and not self._called(tool_messages, "read_file"):
            return ModelResponse.call("read_file", {"path": self._extract_path(goal, ".txt")}, "call_read")

        if self._mentions(goal, "write", "save") and not self._called(tool_messages, "write_file"):
            return ModelResponse.call(
                "write_file",
                {
                    "path": "outputs/agent_note.txt",
                    "content": self._write_content(goal),
                },
                "call_write",
            )

        if self._mentions(goal, "list", "files") and not self._called(tool_messages, "list_files"):
            return ModelResponse.call("list_files", {"path": "."}, "call_list")

        if tool_messages:
            return ModelResponse.final(self._final_from_tool(goal, tool_messages[-1]))

        return ModelResponse.final(
            "I can answer directly, but I did not need any tools for this goal."
        )

    def _goal(self, messages: list[Message]) -> str:
        for message in reversed(messages):
            if message.role == "user":
                return message.content
        return ""

    def _mentions(self, text: str, *needles: str) -> bool:
        lower = text.lower()
        return any(needle in lower for needle in needles)

    def _called(self, tool_messages: list[Message], name: str) -> bool:
        return any(message.name == name for message in tool_messages)

    def _extract_path(self, goal: str, suffix: str) -> str:
        tokens = re.findall(r"[\w./-]+", goal)
        for token in tokens:
            if token.endswith(suffix) or "/" in token:
                return token
        return "data/sample.csv" if suffix == ".csv" else "notes/example.txt"

    def _extract_url(self, goal: str) -> str | None:
        match = re.search(r"https?://[^\s)>\"]+", goal)
        return match.group(0).rstrip(".,;!?") if match else None

    def _search_query(self, goal: str) -> str:
        query = goal
        removals = [
            "search the internet for",
            "search internet for",
            "search the web for",
            "search web for",
            "search latest news about",
            "search news about",
            "search news for",
            "web search for",
            "internet search for",
            "look up",
            "google",
            "latest news about",
            "news about",
            "headlines about",
        ]
        lower = query.lower()
        for phrase in removals:
            if phrase in lower:
                index = lower.index(phrase)
                query = query[:index] + query[index + len(phrase):]
                lower = query.lower()
        return query.strip(" :?.!") or goal

    def _parse_memory_goal(self, goal: str) -> tuple[str, str]:
        lower = goal.lower()
        if "project language" in lower:
            match = re.search(r"project language (?:is|=)\s+([\w.+-]+)", lower)
            value = match.group(1).strip(".,;:!?") if match else goal
            return "project_language", value
        if "preference" in lower:
            return "preference", goal
        return "note", goal

    def _memory_query(self, goal: str) -> str:
        lower = goal.lower()
        if "project language" in lower or "language" in lower:
            return "project_language"
        return goal

    def _write_content(self, goal: str) -> str:
        marker = "saying"
        lower = goal.lower()
        if marker in lower:
            index = lower.index(marker) + len(marker)
            return goal[index:].strip(" :\"'")
        return goal

    def _final_from_tool(self, goal: str, tool_message: Message) -> str:
        try:
            data = json.loads(tool_message.content)
        except json.JSONDecodeError:
            return f"Tool {tool_message.name} returned: {tool_message.content}"

        if tool_message.name == "list_files":
            files = data.get("files", [])
            return f"I found {len(files)} file(s): {', '.join(files)}."

        if tool_message.name == "read_file":
            content = data.get("content", "")
            first_line = content.strip().splitlines()[0] if content.strip() else ""
            return f"I read {data.get('path')}. First line: {first_line}"

        if tool_message.name == "write_file":
            return f"I wrote {data.get('path')}."

        if tool_message.name == "inspect_csv":
            return (
                f"I inspected {data.get('path')}: {data.get('rows')} row(s), "
                f"columns: {', '.join(data.get('columns', []))}."
            )

        if tool_message.name == "remember":
            return f"I remembered {data.get('key')}."

        if tool_message.name == "recall":
            records = data.get("records", [])
            if not records:
                return "I did not find matching memory."
            rendered = ", ".join(f"{item.get('key')}={item.get('value')}" for item in records)
            return f"I found memory: {rendered}."

        if tool_message.name in {"search_web", "search_news"}:
            results = data.get("results", [])
            if not results:
                return f"I did not find results for {data.get('query')}."
            rendered = "; ".join(
                f"{index}. {item.get('title')}"
                for index, item in enumerate(results[:3], start=1)
            )
            return f"I found {len(results)} result(s) from {data.get('source')}: {rendered}."

        if tool_message.name == "fetch_url":
            title = data.get("title") or data.get("url")
            content = data.get("content", "")
            preview = content[:180].strip()
            return f"I fetched {title}. Preview: {preview}"

        return f"Tool {tool_message.name} completed."
