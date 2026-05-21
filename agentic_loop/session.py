from dataclasses import dataclass, field

from .controller import AgentController, AgentResult
from .types import Message


@dataclass
class AgentSession:
    controller: AgentController
    history: list[Message] = field(default_factory=list)

    def ask(self, user_message: str) -> AgentResult:
        result = self.controller.run(user_message, prior_messages=self.history)
        self.history.append(Message(role="user", content=user_message))
        self.history.append(Message(role="assistant", content=result.final_answer))
        return result

    def transcript(self) -> list[dict[str, str]]:
        return [
            {"role": message.role, "content": message.content}
            for message in self.history
            if message.role in {"user", "assistant"}
        ]

