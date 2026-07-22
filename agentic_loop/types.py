from dataclasses import dataclass, field
from typing import Any, Literal


Role = Literal["system", "user", "assistant", "tool"]


@dataclass
class Message:
    role: Role
    content: str
    name: str | None = None
    tool_call_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.name is not None:
            data["name"] = self.name
        if self.tool_call_id is not None:
            data["tool_call_id"] = self.tool_call_id
        return data


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: dict[str, Any]
    id: str = "call_0"


@dataclass(frozen=True)
class ModelResponse:
    final_answer: str | None = None
    tool_call: ToolCall | None = None
    tool_calls: tuple[ToolCall, ...] = ()
    # True when the provider rejected tools and we refused to silently degrade.
    tools_unsupported: bool = False

    def __post_init__(self) -> None:
        # Keep tool_call as the first call for backward-compatible callers.
        if self.tool_calls and self.tool_call is None:
            object.__setattr__(self, "tool_call", self.tool_calls[0])
        elif self.tool_call is not None and not self.tool_calls:
            object.__setattr__(self, "tool_calls", (self.tool_call,))

    @classmethod
    def final(cls, content: str, *, tools_unsupported: bool = False) -> "ModelResponse":
        return cls(final_answer=content, tools_unsupported=tools_unsupported)

    @classmethod
    def call(cls, name: str, arguments: dict[str, Any], call_id: str) -> "ModelResponse":
        tc = ToolCall(name=name, arguments=arguments, id=call_id)
        return cls(tool_call=tc, tool_calls=(tc,))

    @classmethod
    def calls(cls, tool_calls: list[ToolCall] | tuple[ToolCall, ...]) -> "ModelResponse":
        calls = tuple(tool_calls)
        if not calls:
            return cls.final("Model returned an empty tool-call list.")
        return cls(tool_call=calls[0], tool_calls=calls)


@dataclass
class PolicyDecision:
    allowed: bool
    reason: str = ""
    requires_approval: bool = False


@dataclass
class ToolResult:
    ok: bool
    content: Any
    error: str | None = None


@dataclass
class AgentStep:
    index: int
    action: str
    tool_name: str | None = None
    arguments: dict[str, Any] = field(default_factory=dict)
    observation: Any = None
    allowed: bool = True
    error: str | None = None


@dataclass
class AgentState:
    goal: str
    steps: list[AgentStep] = field(default_factory=list)
    final_answer: str | None = None

    def add_step(self, step: AgentStep) -> None:
        self.steps.append(step)

    def summary(self, max_steps: int = 5) -> str:
        recent = self.steps[-max_steps:]
        if not recent:
            return "No steps have run yet."
        lines = []
        for step in recent:
            if step.tool_name:
                status = "allowed" if step.allowed else "denied"
                lines.append(f"{step.index}. {step.tool_name} ({status})")
            else:
                lines.append(f"{step.index}. {step.action}")
        return "\n".join(lines)
