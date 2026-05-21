from dataclasses import dataclass
from pathlib import Path
import uuid
from typing import Any

from .context import ContextBuilder
from .evals import BasicEvaluator
from .logs import JsonlTraceLogger
from .memory import MemoryStore
from .model import AgentModel
from .policy import WorkspacePolicy
from .tools import ToolContext, ToolRegistry, WebClient, serialize_tool_result
from .types import AgentState, AgentStep, Message


@dataclass
class AgentResult:
    final_answer: str
    state: AgentState
    evaluation: dict[str, object]
    run_id: str


class AgentController:
    def __init__(
        self,
        model: AgentModel,
        tools: ToolRegistry,
        policy: WorkspacePolicy,
        workspace_root: str | Path,
        memory: MemoryStore | None = None,
        context_builder: ContextBuilder | None = None,
        logger: JsonlTraceLogger | None = None,
        max_steps: int = 8,
        storage: Any = None,
        web_client: WebClient | None = None,
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
        self.storage = storage
        self.web_client = web_client

    def run(
        self,
        goal: str,
        prior_messages: list[Message] | None = None,
        session_id: str | None = None,
        run_id: str | None = None,
    ) -> AgentResult:
        run_id = run_id or uuid.uuid4().hex
        state = AgentState(goal=goal)
        messages = self.context_builder.initial_messages(goal, prior_messages)
        tool_context = ToolContext(
            workspace_root=self.workspace_root,
            memory=self.memory,
            web_client=self.web_client,
        )

        self.logger.log(
            "run_started",
            {"goal": goal, "policy": self.policy.describe()},
            session_id=session_id,
            run_id=run_id,
        )

        for index in range(1, self.max_steps + 1):
            context_message = self.context_builder.state_message(state, self.memory)
            model_messages = [messages[0], context_message, *messages[1:]]
            self.logger.log(
                "model_requested",
                {
                    "step_index": index,
                    "message_count": len(model_messages),
                    "tool_count": len(self.tools.schemas()),
                    "state_summary": state.summary(),
                },
                session_id=session_id,
                run_id=run_id,
            )
            response = self.model.respond(
                model_messages,
                tools=self.tools.schemas(),
                state_summary=state.summary(),
            )

            if response.final_answer is not None:
                state.final_answer = response.final_answer
                state.add_step(AgentStep(index=index, action="final_answer"))
                self.logger.log(
                    "final_answer",
                    {"content": response.final_answer},
                    session_id=session_id,
                    run_id=run_id,
                )
                return self._result(
                    state=state,
                    final_answer=response.final_answer,
                    run_id=run_id,
                    session_id=session_id,
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
                    "requires_approval": decision.requires_approval,
                },
                session_id=session_id,
                run_id=run_id,
            )

            if not decision.allowed:
                denial = f"Tool call denied by policy: {decision.reason}"
                action = "approval_required" if decision.requires_approval else "tool_denied"
                state.add_step(
                    AgentStep(
                        index=index,
                        action=action,
                        tool_name=call.name,
                        arguments=call.arguments,
                        observation=denial,
                        allowed=False,
                    )
                )
                if decision.requires_approval:
                    self.logger.log(
                        "approval_required",
                        {"tool": call.name, "arguments": call.arguments, "reason": decision.reason},
                        session_id=session_id,
                        run_id=run_id,
                    )
                self._log_state_delta(state, session_id, run_id)
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
                self.logger.log(
                    "tool_result",
                    {"tool": call.name, "result": result},
                    session_id=session_id,
                    run_id=run_id,
                )
                if call.name == "remember":
                    self.logger.log(
                        "memory_written",
                        {"record": result},
                        session_id=session_id,
                        run_id=run_id,
                    )
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
                self.logger.log(
                    "tool_error",
                    {"tool": call.name, "error": serialized},
                    session_id=session_id,
                    run_id=run_id,
                )

            self._log_state_delta(state, session_id, run_id)

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
        self.logger.log(
            "max_steps_reached",
            {"max_steps": self.max_steps},
            session_id=session_id,
            run_id=run_id,
        )
        self.logger.log(
            "final_answer",
            {"content": state.final_answer},
            session_id=session_id,
            run_id=run_id,
        )
        return self._result(
            state=state,
            final_answer=state.final_answer,
            run_id=run_id,
            session_id=session_id,
        )

    def _log_state_delta(
        self,
        state: AgentState,
        session_id: str | None,
        run_id: str,
    ) -> None:
        self.logger.log(
            "state_delta",
            {"steps": len(state.steps), "summary": state.summary()},
            session_id=session_id,
            run_id=run_id,
        )

    def _result(
        self,
        state: AgentState,
        final_answer: str,
        run_id: str,
        session_id: str | None,
    ) -> AgentResult:
        evaluation = self.evaluator.evaluate(state)
        if self.storage is not None:
            self.storage.save_run_result(
                run_id,
                session_id,
                state.goal,
                final_answer,
                evaluation,
                state.steps,
            )
        return AgentResult(
            final_answer=final_answer,
            state=state,
            evaluation=evaluation,
            run_id=run_id,
        )
