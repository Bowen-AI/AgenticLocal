from dataclasses import dataclass
import json
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

            repeated_step = self._find_successful_repeated_tool_step(
                state,
                call.name,
                call.arguments,
            )
            if repeated_step is not None:
                final_answer = self._final_from_tool_result(call.name, repeated_step.observation)
                state.final_answer = final_answer
                state.add_step(
                    AgentStep(
                        index=index,
                        action="repeated_tool_finalized",
                        tool_name=call.name,
                        arguments=call.arguments,
                        observation=repeated_step.observation,
                    )
                )
                self.logger.log(
                    "tool_repeated",
                    {
                        "tool": call.name,
                        "arguments": call.arguments,
                        "previous_step_index": repeated_step.index,
                    },
                    session_id=session_id,
                    run_id=run_id,
                )
                self._log_state_delta(state, session_id, run_id)
                self.logger.log(
                    "final_answer",
                    {"content": final_answer},
                    session_id=session_id,
                    run_id=run_id,
                )
                return self._result(
                    state=state,
                    final_answer=final_answer,
                    run_id=run_id,
                    session_id=session_id,
                )

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

    def _find_successful_repeated_tool_step(
        self,
        state: AgentState,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> AgentStep | None:
        signature = self._tool_signature(tool_name, arguments)
        for step in reversed(state.steps):
            if (
                step.action == "tool_call"
                and step.allowed
                and step.error is None
                and self._tool_signature(step.tool_name or "", step.arguments) == signature
            ):
                return step
        return None

    def _tool_signature(self, tool_name: str, arguments: dict[str, Any]) -> str:
        return json.dumps(
            {"tool": tool_name, "arguments": arguments},
            sort_keys=True,
            default=str,
        )

    def _final_from_tool_result(self, tool_name: str, result: Any) -> str:
        if not isinstance(result, dict):
            return f"Tool {tool_name} already returned: {result}"

        if tool_name == "list_files":
            files = result.get("files", [])
            return f"I found {len(files)} file(s): {', '.join(files)}."

        if tool_name == "read_file":
            content = result.get("content", "")
            first_line = content.strip().splitlines()[0] if content.strip() else ""
            return f"I read {result.get('path')}. First line: {first_line}"

        if tool_name == "write_file":
            return f"I wrote {result.get('path')}."

        if tool_name == "inspect_csv":
            return (
                f"I inspected {result.get('path')}: {result.get('rows')} row(s), "
                f"columns: {', '.join(result.get('columns', []))}."
            )

        if tool_name == "remember":
            return f"I remembered {result.get('key')}."

        if tool_name == "recall":
            records = result.get("records", [])
            if not records:
                return "I did not find matching memory."
            rendered = ", ".join(f"{item.get('key')}={item.get('value')}" for item in records)
            return f"I found memory: {rendered}."

        if tool_name == "current_datetime":
            return (
                f"Today is {result.get('weekday')}, {result.get('date')}. "
                f"The local time is {result.get('time')} {result.get('timezone')}."
            )

        if tool_name in {"search_web", "search_news"}:
            results = result.get("results", [])
            if not results:
                return f"I did not find results for {result.get('query')}."
            rendered = "; ".join(
                f"{index}. {item.get('title')}"
                for index, item in enumerate(results[:3], start=1)
            )
            return f"I found {len(results)} result(s) from {result.get('source')}: {rendered}."

        if tool_name == "fetch_url":
            title = result.get("title") or result.get("url")
            content = result.get("content", "")
            preview = content[:180].strip()
            return f"I fetched {title}. Preview: {preview}"

        return f"Tool {tool_name} already completed."

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
