from dataclasses import dataclass, field
from typing import Any

from .types import PolicyDecision, ToolCall


@dataclass(frozen=True)
class RuleDefinition:
    key: str
    label: str
    description: str
    category: str
    prompt_text: str
    policy: dict[str, Any] = field(default_factory=dict)
    default_enabled: bool = False
    priority: int = 100

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RuleDefinition":
        return cls(
            key=data["key"],
            label=data.get("label", data["key"]),
            description=data.get("description", ""),
            category=data.get("category", "general"),
            prompt_text=data.get("prompt_text", ""),
            policy=dict(data.get("policy") or {}),
            default_enabled=bool(data.get("default_enabled", False)),
            priority=int(data.get("priority", 100)),
        )

    def to_dict(self, enabled: bool | None = None) -> dict[str, Any]:
        payload = {
            "key": self.key,
            "label": self.label,
            "description": self.description,
            "category": self.category,
            "prompt_text": self.prompt_text,
            "policy": self.policy,
            "default_enabled": self.default_enabled,
            "priority": self.priority,
        }
        if enabled is not None:
            payload["enabled"] = enabled
        return payload


@dataclass(frozen=True)
class WorkflowDefinition:
    key: str
    command: str
    description: str
    rule_keys: tuple[str, ...] = ()
    max_steps_override: int | None = None
    required_tools: tuple[str, ...] = ()
    prompt_prefix: str = ""
    enabled: bool = True

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorkflowDefinition":
        return cls(
            key=data["key"],
            command=data.get("command") or f"/{data['key']}",
            description=data.get("description", ""),
            rule_keys=tuple(data.get("rule_keys") or ()),
            max_steps_override=data.get("max_steps_override"),
            required_tools=tuple(data.get("required_tools") or ()),
            prompt_prefix=data.get("prompt_prefix", ""),
            enabled=bool(data.get("enabled", True)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "command": self.command,
            "description": self.description,
            "rule_keys": list(self.rule_keys),
            "max_steps_override": self.max_steps_override,
            "required_tools": list(self.required_tools),
            "prompt_prefix": self.prompt_prefix,
            "enabled": self.enabled,
        }


DEFAULT_RULES = [
    RuleDefinition(
        key="max_effort",
        label="Max Effort",
        description="Ask the model to spend extra effort on planning and verification.",
        category="effort",
        prompt_text=(
            "Use maximum practical effort: reason carefully, verify tool results, "
            "and do not stop until the task is genuinely handled."
        ),
        priority=10,
    ),
    RuleDefinition(
        key="academic",
        label="Academic",
        description="Prefer careful sourcing language and a more formal explanatory tone.",
        category="style",
        prompt_text=(
            "Use an academic style: define terms, distinguish evidence from inference, "
            "and avoid overstating uncertain claims."
        ),
        priority=30,
    ),
    RuleDefinition(
        key="concise",
        label="Concise",
        description="Keep final answers short unless detail is needed for correctness.",
        category="style",
        prompt_text="Be concise and prioritize the highest-signal details in the final answer.",
        priority=40,
    ),
    RuleDefinition(
        key="safe_writes",
        label="Safe Writes",
        description="Require human approval before write tools mutate workspace files.",
        category="safety",
        prompt_text=(
            "Before writing files, make the intended change explicit and expect a "
            "human approval checkpoint."
        ),
        policy={"require_write_approval": True},
        priority=5,
    ),
]


DEFAULT_WORKFLOWS = [
    WorkflowDefinition(
        key="loop",
        command="/loop",
        description="Run with extra deliberation and a larger step budget.",
        rule_keys=("max_effort",),
        max_steps_override=12,
        prompt_prefix=(
            "Workflow /loop is active. Work deliberately through the loop: inspect, "
            "act, observe, and finalize only when the goal is complete."
        ),
    ),
    WorkflowDefinition(
        key="search",
        command="/search",
        description="Run a web-search-focused task using network search tools.",
        rule_keys=("max_effort",),
        max_steps_override=10,
        required_tools=("search_web",),
        prompt_prefix=(
            "Workflow /search is active. Prefer search_web or search_news for current "
            "or external information, then synthesize the result."
        ),
    ),
]


def default_rule_metadata() -> list[dict[str, Any]]:
    return [rule.to_dict() for rule in DEFAULT_RULES]


def default_workflow_metadata() -> list[dict[str, Any]]:
    return [workflow.to_dict() for workflow in DEFAULT_WORKFLOWS]


class RuleResolver:
    def __init__(self, storage: Any = None):
        self.storage = storage

    def rules(self) -> list[RuleDefinition]:
        if self.storage is None:
            return sorted(DEFAULT_RULES, key=lambda rule: (rule.priority, rule.key))
        return sorted(
            [RuleDefinition.from_dict(item) for item in self.storage.list_rule_registry()],
            key=lambda rule: (rule.priority, rule.key),
        )

    def workflows(self) -> list[WorkflowDefinition]:
        if self.storage is None:
            return sorted(DEFAULT_WORKFLOWS, key=lambda workflow: workflow.key)
        return sorted(
            [WorkflowDefinition.from_dict(item) for item in self.storage.list_workflow_registry()],
            key=lambda workflow: workflow.key,
        )

    def workflow(self, key_or_command: str | None) -> WorkflowDefinition | None:
        if not key_or_command:
            return None
        normalized = key_or_command.strip()
        for workflow in self.workflows():
            if normalized in {workflow.key, workflow.command}:
                return workflow
        return None

    def rules_with_state(
        self,
        session_id: str | None = None,
        run_id: str | None = None,
        enabled_rule_keys: set[str] | None = None,
        disabled_rule_keys: set[str] | None = None,
        workflow: WorkflowDefinition | None = None,
    ) -> list[dict[str, Any]]:
        enabled_keys = {rule.key for rule in self.active_rules(
            session_id=session_id,
            run_id=run_id,
            enabled_rule_keys=enabled_rule_keys,
            disabled_rule_keys=disabled_rule_keys,
            workflow=workflow,
        )}
        return [rule.to_dict(enabled=rule.key in enabled_keys) for rule in self.rules()]

    def active_rules(
        self,
        session_id: str | None = None,
        run_id: str | None = None,
        enabled_rule_keys: set[str] | None = None,
        disabled_rule_keys: set[str] | None = None,
        workflow: WorkflowDefinition | None = None,
    ) -> list[RuleDefinition]:
        enabled_rule_keys = set(enabled_rule_keys or ())
        disabled_rule_keys = set(disabled_rule_keys or ())
        states = {rule.key: rule.default_enabled for rule in self.rules()}
        for scope_type, scope_id in (("global", ""), ("session", session_id or "")):
            if self.storage is None or (scope_type != "global" and not scope_id):
                continue
            for setting in self.storage.list_rule_settings(scope_type, scope_id):
                if setting["rule_key"] in states:
                    states[setting["rule_key"]] = bool(setting["enabled"])

        if workflow is not None:
            for key in workflow.rule_keys:
                if key in states:
                    states[key] = True
        if self.storage is not None and run_id:
            for setting in self.storage.list_rule_settings("run", run_id):
                if setting["rule_key"] in states:
                    states[setting["rule_key"]] = bool(setting["enabled"])
        for key in enabled_rule_keys:
            if key in states:
                states[key] = True
        for key in disabled_rule_keys:
            if key in states:
                states[key] = False

        return [rule for rule in self.rules() if states.get(rule.key, False)]

    def policy_decision(
        self,
        call: ToolCall,
        active_rules: list[RuleDefinition],
    ) -> PolicyDecision:
        for rule in active_rules:
            if rule.policy.get("require_write_approval") and call.name == "write_file":
                return PolicyDecision(
                    False,
                    f"active rule {rule.key} requires approval before write_file",
                    requires_approval=True,
                )
            disabled_tools = set(rule.policy.get("disabled_tools") or ())
            if call.name in disabled_tools:
                return PolicyDecision(
                    False,
                    f"active rule {rule.key} disables tool: {call.name}",
                )
        return PolicyDecision(True, "allowed by active rules")
