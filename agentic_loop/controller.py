from dataclasses import dataclass
from pathlib import Path

from .context import ContextBuilder
from .evals import BasicEvaluator
from .logs import JsonlTraceLogger
from .memory import JsonlMemory
from .model import AgentModel
from .policy import WorkspacePolicy
from .tools import ToolContext, ToolRegistry, serialize_tool_result
from .types import AgentState, AgentStep, Message


@dataclass
class AgentResult:
    final_answer: str
    state: AgentState
    evaluation: dict[str, object]


class AgentController:
    def __init__(
        self,
        model: AgentModel,
        tools: ToolRegistry,
        policy: WorkspacePolicy,
        workspace_root: str | Path,
        memory: JsonlMemory | None = None,
        context_builder: ContextBuilder | None = None,
        logger: JsonlTraceLogger | None = None,
        max_steps: int = 8,
    ):
        self.model = model
        self.tools = tools
        self.policy = policy
        self.workspace_root = Path(workspace_root).resolve()
        self.memory = memory
        self.context_builder = context_builder or ContextBuilder()
        self.logger = logger or JsonlTraceLogger()
        self.max_steps = max_steps
        self.evaluator = BasicEvaluator(self.workspace_root)

    def run(
        self,
        goal: str,
        prior_messages: list[Message] | None = None,
    ) -> AgentResult:
        state = AgentState(goal=goal)
        messages = self.context_builder.initial_messages(goal, prior_messages)
        tool_context = ToolContext(workspace_root=self.workspace_root, memory=self.memory)

        self.logger.log("agent_started", {"goal": goal, "policy": self.policy.describe()})

        for index in range(1, self.max_steps + 1):
            context_message = self.context_builder.state_message(state, self.memory)
            model_messages = [messages[0], context_message, *messages[1:]]
            response = self.model.respond(
                model_messages,
                tools=self.tools.schemas(),
                state_summary=state.summary(),
            )

            if response.final_answer is not None:
                state.final_answer = response.final_answer
                state.add_step(AgentStep(index=index, action="final_answer"))
                self.logger.log("final_answer", {"content": response.final_answer})
                return AgentResult(
                    final_answer=response.final_answer,
                    state=state,
                    evaluation=self.evaluator.evaluate(state),
                )

            if response.tool_call is None:
                state.final_answer = "Model returned neither a tool call nor a final answer."
                state.add_step(
                    AgentStep(index=index, action="invalid_model_response", error=state.final_answer)
                )
                break

            call = response.tool_call
            decision = self.policy.check(call)
            self.logger.log(
                "tool_requested",
                {
                    "tool": call.name,
                    "arguments": call.arguments,
                    "allowed": decision.allowed,
                    "reason": decision.reason,
                },
            )

            if not decision.allowed:
                denial = f"Tool call denied by policy: {decision.reason}"
                state.add_step(
                    AgentStep(
                        index=index,
                        action="tool_denied",
                        tool_name=call.name,
                        arguments=call.arguments,
                        observation=denial,
                        allowed=False,
                    )
                )
                messages.append(Message(role="assistant", content=f"Tool call requested: {call.name}"))
                messages.append(
                    Message(
                        role="tool",
                        name=call.name,
                        tool_call_id=call.id,
                        content=denial,
                    )
                )
                continue

            try:
                result = self.tools.run(call.name, tool_context, call.arguments)
                serialized = serialize_tool_result(result)
                state.add_step(
                    AgentStep(
                        index=index,
                        action="tool_call",
                        tool_name=call.name,
                        arguments=call.arguments,
                        observation=result,
                    )
                )
                self.logger.log("tool_result", {"tool": call.name, "result": result})
            except Exception as exc:
                serialized = f"{type(exc).__name__}: {exc}"
                state.add_step(
                    AgentStep(
                        index=index,
                        action="tool_error",
                        tool_name=call.name,
                        arguments=call.arguments,
                        allowed=True,
                        error=serialized,
                    )
                )
                self.logger.log("tool_error", {"tool": call.name, "error": serialized})

            messages.append(Message(role="assistant", content=f"Tool call requested: {call.name}"))
            messages.append(
                Message(
                    role="tool",
                    name=call.name,
                    tool_call_id=call.id,
                    content=serialized,
                )
            )

        state.final_answer = "Agent stopped because the step limit was reached."
        self.logger.log("max_steps_reached", {"max_steps": self.max_steps})
        return AgentResult(
            final_answer=state.final_answer,
            state=state,
            evaluation=self.evaluator.evaluate(state),
        )
