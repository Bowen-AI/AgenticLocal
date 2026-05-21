from dataclasses import dataclass, field
from typing import Any

from .controller import AgentController, AgentResult
from .types import Message


@dataclass
class AgentSession:
    controller: AgentController
    history: list[Message] = field(default_factory=list)
    session_id: str | None = None
    storage: Any = None

    def ask(
        self,
        user_message: str,
        enabled_rule_keys: list[str] | tuple[str, ...] | set[str] | None = None,
        disabled_rule_keys: list[str] | tuple[str, ...] | set[str] | None = None,
        workflow_key: str | None = None,
    ) -> AgentResult:
        result = self.controller.run(
            user_message,
            prior_messages=self.history,
            session_id=self.session_id,
            enabled_rule_keys=enabled_rule_keys,
            disabled_rule_keys=disabled_rule_keys,
            workflow_key=workflow_key,
        )
        user = Message(role="user", content=user_message)
        assistant = Message(role="assistant", content=result.final_answer)
        self.history.append(user)
        self.history.append(assistant)
        if self.storage is not None and self.session_id is not None:
            self.storage.append_message(self.session_id, user)
            self.storage.append_message(self.session_id, assistant)
            if getattr(self.controller, "storage", None) is None:
                self.storage.save_run_result(
                    result.run_id,
                    self.session_id,
                    result.state.goal,
                    result.final_answer,
                    result.evaluation,
                    result.state.steps,
                )
        return result

    def transcript(self) -> list[dict[str, str]]:
        return [
            {"role": message.role, "content": message.content}
            for message in self.history
            if message.role in {"user", "assistant"}
        ]
