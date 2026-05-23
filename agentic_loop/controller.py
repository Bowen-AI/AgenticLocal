from dataclasses import dataclass
import json
from pathlib import Path
import uuid
from typing import Any

from .context import ContextBuilder
from .evals import BasicEvaluator
from .learning import (
    normalize_learning_mode,
    record_learning_result,
    record_skill_use_results,
    relevant_skills,
)
from .logs import JsonlTraceLogger
from .memory import MemoryStore
from .model import AgentModel
from .policy import WorkspacePolicy
from .rules import RuleResolver, WorkflowDefinition
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
        rule_resolver: RuleResolver | None = None,
        enabled_rule_keys: list[str] | tuple[str, ...] | set[str] | None = None,
        disabled_rule_keys: list[str] | tuple[str, ...] | set[str] | None = None,
        workflow_key: str | None = None,
        tool_context: ToolContext | None = None,
        learning_mode: str = "draft",
        learning_threshold: int = 2,
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
        self.rule_resolver = rule_resolver or RuleResolver(storage)
        self.enabled_rule_keys = set(enabled_rule_keys or ())
        self.disabled_rule_keys = set(disabled_rule_keys or ())
        self.workflow_key = workflow_key
        self.tool_context = tool_context
        self.learning_mode = normalize_learning_mode(learning_mode)
        self.learning_threshold = learning_threshold

    def run(
        self,
        goal: str,
        prior_messages: list[Message] | None = None,
        session_id: str | None = None,
        run_id: str | None = None,
        enabled_rule_keys: list[str] | tuple[str, ...] | set[str] | None = None,
        disabled_rule_keys: list[str] | tuple[str, ...] | set[str] | None = None,
        workflow_key: str | None = None,
    ) -> AgentResult:
        run_id = run_id or uuid.uuid4().hex
        state = AgentState(goal=goal)
        run_enabled_rules = set(self.enabled_rule_keys)
        run_enabled_rules.update(enabled_rule_keys or ())
        run_disabled_rules = set(self.disabled_rule_keys)
        run_disabled_rules.update(disabled_rule_keys or ())
        workflow = self._resolve_workflow(workflow_key or self.workflow_key)
        workflow_error = self._workflow_error(workflow_key or self.workflow_key, workflow)
        if workflow_error is not None:
            state.final_answer = workflow_error
            state.add_step(AgentStep(index=1, action="workflow_unavailable", error=workflow_error))
            self.logger.log(
                "workflow_unavailable",
                {"workflow": workflow_key or self.workflow_key, "error": workflow_error},
                session_id=session_id,
                run_id=run_id,
            )
            self.logger.log(
                "final_answer",
                {"content": workflow_error},
                session_id=session_id,
                run_id=run_id,
            )
            return self._result(
                state,
                workflow_error,
                run_id,
                session_id,
                workflow_key=workflow_key or self.workflow_key,
                active_rule_keys=[],
                matched_skills=[],
            )

        messages = self.context_builder.initial_messages(
            goal,
            prior_messages,
            workflow_prompt=workflow.prompt_prefix if workflow else None,
        )
        tool_context = self._tool_context()
        run_max_steps = workflow.max_steps_override if workflow and workflow.max_steps_override else self.max_steps
        matched_skills = self._matched_learning_skills(goal)
        active_rule_keys_for_learning: list[str] = []

        self.logger.log(
            "run_started",
            {
                "goal": goal,
                "policy": self.policy.describe(),
                "workflow": workflow.key if workflow else None,
            },
            session_id=session_id,
            run_id=run_id,
        )

        for index in range(1, run_max_steps + 1):
            active_rules = self.rule_resolver.active_rules(
                session_id=session_id,
                run_id=run_id,
                enabled_rule_keys=run_enabled_rules,
                disabled_rule_keys=run_disabled_rules,
                workflow=workflow,
            )
            context_message = self.context_builder.state_message(
                state,
                self.memory,
                active_rules=active_rules,
                active_skills=matched_skills,
            )
            active_rule_keys_for_learning = [rule.key for rule in active_rules]
            model_messages = [messages[0], context_message, *messages[1:]]
            self.logger.log(
                "model_requested",
                {
                    "step_index": index,
                    "message_count": len(model_messages),
                    "tool_count": len(self.tools.schemas()),
                    "state_summary": state.summary(),
                    "active_rules": [rule.key for rule in active_rules],
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
                    workflow_key=workflow.key if workflow else None,
                    active_rule_keys=active_rule_keys_for_learning,
                    matched_skills=matched_skills,
                )

            if response.tool_call is None:
                state.final_answer = "Model returned neither a tool call nor a final answer."
                state.add_step(
                    AgentStep(index=index, action="invalid_model_response", error=state.final_answer)
                )
                break

            call = response.tool_call
            active_rules = self.rule_resolver.active_rules(
                session_id=session_id,
                run_id=run_id,
                enabled_rule_keys=run_enabled_rules,
                disabled_rule_keys=run_disabled_rules,
                workflow=workflow,
            )
            decision = self.policy.check(call)
            if decision.allowed:
                decision = self.rule_resolver.policy_decision(call, active_rules)
            self.logger.log(
                "tool_requested",
                {
                    "tool": call.name,
                    "arguments": call.arguments,
                    "allowed": decision.allowed,
                    "reason": decision.reason,
                    "requires_approval": decision.requires_approval,
                    "active_rules": [rule.key for rule in active_rules],
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
                    workflow_key=workflow.key if workflow else None,
                    active_rule_keys=active_rule_keys_for_learning,
                    matched_skills=matched_skills,
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
            {"max_steps": run_max_steps},
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
            workflow_key=workflow.key if workflow else None,
            active_rule_keys=active_rule_keys_for_learning,
            matched_skills=matched_skills,
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
        workflow_key: str | None = None,
        active_rule_keys: list[str] | None = None,
        matched_skills: list[dict[str, Any]] | None = None,
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
            try:
                learning = record_learning_result(
                    self.storage,
                    state=state,
                    final_answer=final_answer,
                    evaluation=evaluation,
                    run_id=run_id,
                    session_id=session_id,
                    learning_mode=self.learning_mode,
                    learning_threshold=self.learning_threshold,
                    workflow=workflow_key,
                    active_rules=active_rule_keys,
                )
                experience = learning.get("experience") or {}
                record_skill_use_results(
                    self.storage,
                    matched_skills or [],
                    run_id=run_id,
                    session_id=session_id,
                    outcome=experience.get("outcome") or "unknown",
                )
            except Exception as exc:
                self.logger.log(
                    "learning_error",
                    {"error": f"{type(exc).__name__}: {exc}"},
                    session_id=session_id,
                    run_id=run_id,
                )
        return AgentResult(
            final_answer=final_answer,
            state=state,
            evaluation=evaluation,
            run_id=run_id,
        )

    def _resolve_workflow(self, workflow_key: str | None) -> WorkflowDefinition | None:
        return self.rule_resolver.workflow(workflow_key)

    def _tool_context(self) -> ToolContext:
        if self.tool_context is None:
            return ToolContext(
                workspace_root=self.workspace_root,
                memory=self.memory,
                web_client=self.web_client,
            )
        self.tool_context.workspace_root = self.workspace_root
        self.tool_context.memory = self.memory
        self.tool_context.web_client = self.web_client
        return self.tool_context

    def _matched_learning_skills(self, goal: str) -> list[dict[str, Any]]:
        if self.learning_mode == "off" or self.storage is None:
            return []
        try:
            return relevant_skills(self.storage, goal)
        except Exception as exc:
            self.logger.log(
                "learning_error",
                {"error": f"{type(exc).__name__}: {exc}"},
            )
            return []

    def _workflow_error(
        self,
        workflow_key: str | None,
        workflow: WorkflowDefinition | None,
    ) -> str | None:
        if not workflow_key:
            return None
        if workflow is None:
            return f"Unknown workflow: {workflow_key}."
        if not workflow.enabled:
            return f"Workflow {workflow.command} is disabled."
        missing_tools = sorted(set(workflow.required_tools) - self.tools.names())
        if missing_tools:
            missing = ", ".join(missing_tools)
            return (
                f"Workflow {workflow.command} requires unavailable tool(s): {missing}. "
                "Start with --enable-network-tools."
            )
        return None
