import json

from .memory import MemoryStore
from .types import AgentState, Message


SYSTEM_PROMPT = """You are a small agent runtime demonstration.

You can decide to answer directly or request one approved tool call.
The runtime, not you, executes tools and enforces policy.
Use tools when you need file, data, or memory access.
"""


class ContextBuilder:
    def __init__(self, system_prompt: str = SYSTEM_PROMPT):
        self.system_prompt = system_prompt

    def initial_messages(
        self,
        goal: str,
        prior_messages: list[Message] | None = None,
    ) -> list[Message]:
        messages = [Message(role="system", content=self.system_prompt.strip())]
        messages.extend(prior_messages or [])
        messages.append(Message(role="user", content=goal))
        return messages

    def state_message(self, state: AgentState, memory: MemoryStore | None = None) -> Message:
        memory_lines = []
        if memory:
            for record in memory.search(state.goal):
                memory_lines.append(f"- {record.key}: {json.dumps(record.value)}")

        content = [
            "Current agent state:",
            f"Goal: {state.goal}",
            "Recent steps:",
            state.summary(),
        ]
        if memory_lines:
            content.append("Relevant memory:")
            content.extend(memory_lines)

        return Message(role="system", content="\n".join(content))
