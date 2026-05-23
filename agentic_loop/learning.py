import re
from dataclasses import dataclass, field
from typing import Any

from .skills import match_skills, render_skill_markdown, slugify_skill_key
from .types import AgentState


LEARNING_MODES = {"off", "draft", "auto"}
SECRET_RE = re.compile(
    r"(?i)(api[_-]?key|token|secret|password)\s*[:=]\s*[^\s,;]+|"
    r"(sk-[A-Za-z0-9_-]{12,})"
)
WORD_RE = re.compile(r"[a-z0-9][a-z0-9_-]*")
STOPWORDS = {
    "about",
    "after",
    "again",
    "agent",
    "agentic",
    "answer",
    "before",
    "from",
    "have",
    "into",
    "that",
    "this",
    "with",
    "would",
    "your",
}


@dataclass
class ExperienceSummary:
    run_id: str
    session_id: str | None
    goal: str
    outcome: str
    final_answer: str
    evaluation: dict[str, Any]
    tools: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    denied_actions: list[str] = field(default_factory=list)
    workflow: str | None = None
    active_rules: list[str] = field(default_factory=list)
    signature: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "session_id": self.session_id,
            "goal": self.goal,
            "outcome": self.outcome,
            "final_answer": self.final_answer,
            "evaluation": self.evaluation,
            "tools": list(self.tools),
            "errors": list(self.errors),
            "denied_actions": list(self.denied_actions),
            "workflow": self.workflow,
            "active_rules": list(self.active_rules),
            "signature": self.signature,
        }


@dataclass
class ReflectionRecord:
    outcome: str
    what_worked: list[str] = field(default_factory=list)
    what_failed: list[str] = field(default_factory=list)
    repeatable_pattern: str | None = None
    candidate_memory: dict[str, Any] | None = None
    candidate_skill: dict[str, Any] | None = None
    candidate_anti_pattern: dict[str, Any] | None = None
    verification: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome,
            "what_worked": list(self.what_worked),
            "what_failed": list(self.what_failed),
            "repeatable_pattern": self.repeatable_pattern,
            "candidate_memory": self.candidate_memory,
            "candidate_skill": self.candidate_skill,
            "candidate_anti_pattern": self.candidate_anti_pattern,
            "verification": list(self.verification),
        }


def normalize_learning_mode(value: str | None) -> str:
    mode = (value or "draft").strip().lower()
    if mode not in LEARNING_MODES:
        allowed = ", ".join(sorted(LEARNING_MODES))
        raise ValueError(f"learning must be one of: {allowed}")
    return mode


def summarize_experience(
    state: AgentState,
    final_answer: str,
    evaluation: dict[str, Any],
    run_id: str,
    session_id: str | None = None,
    workflow: str | None = None,
    active_rules: list[str] | None = None,
) -> ExperienceSummary:
    tools = []
    errors = []
    denied_actions = []
    for step in state.steps:
        if step.tool_name and step.tool_name not in tools:
            tools.append(step.tool_name)
        if step.error:
            errors.append(_safe_text(step.error, limit=500))
        if not step.allowed:
            reason = step.observation if step.observation is not None else step.action
            denied_actions.append(_safe_text(str(reason), limit=500))

    if denied_actions:
        outcome = "blocked"
    elif errors or evaluation.get("tool_errors"):
        outcome = "error"
    elif evaluation.get("has_final_answer"):
        outcome = "success"
    else:
        outcome = "unknown"

    signature = _experience_signature(state.goal, tools, workflow)
    return ExperienceSummary(
        run_id=run_id,
        session_id=session_id,
        goal=_safe_text(state.goal, limit=1000),
        outcome=outcome,
        final_answer=_safe_text(final_answer, limit=2000),
        evaluation=evaluation,
        tools=tools,
        errors=errors,
        denied_actions=denied_actions,
        workflow=workflow,
        active_rules=active_rules or [],
        signature=signature,
    )


def reflect_experience(
    summary: ExperienceSummary | dict[str, Any],
    recurrence_count: int = 1,
    threshold: int = 2,
    user_corrected: bool = False,
) -> ReflectionRecord:
    data = summary.to_dict() if isinstance(summary, ExperienceSummary) else dict(summary)
    tools = [str(item) for item in data.get("tools") or []]
    errors = [str(item) for item in data.get("errors") or []]
    denied_actions = [str(item) for item in data.get("denied_actions") or []]
    outcome = str(data.get("outcome") or "unknown")
    what_worked = []
    what_failed = []
    verification = []
    if tools and outcome == "success":
        what_worked.append(f"Used {', '.join(tools)} successfully.")
    elif outcome == "success":
        what_worked.append("Answered directly with a final response.")
    if errors:
        what_failed.extend(errors[:3])
    if denied_actions:
        what_failed.extend(denied_actions[:3])
    if data.get("evaluation"):
        verification.append("Review stored evaluation fields before approving the learning artifact.")

    candidate_memory = _candidate_memory(data) if outcome == "success" else None
    repeatable_pattern = None
    candidate_skill = None
    if tools and outcome == "success":
        repeatable_pattern = _pattern_sentence(data, tools)
        if recurrence_count >= threshold or user_corrected:
            candidate_skill = _candidate_skill(data, tools)

    candidate_anti_pattern = None
    if outcome in {"blocked", "error"} and (errors or denied_actions):
        title = "Avoid repeating a failed action"
        key = slugify_skill_key(f"avoid {data.get('signature') or data.get('goal')}", "avoid-failed-action")
        candidate_anti_pattern = {
            "key": key,
            "title": title,
            "value": {
                "goal": data.get("goal"),
                "outcome": outcome,
                "errors": errors[:3],
                "denied_actions": denied_actions[:3],
            },
        }

    return ReflectionRecord(
        outcome=outcome,
        what_worked=what_worked,
        what_failed=what_failed,
        repeatable_pattern=repeatable_pattern,
        candidate_memory=candidate_memory,
        candidate_skill=candidate_skill,
        candidate_anti_pattern=candidate_anti_pattern,
        verification=verification,
    )


def record_learning_result(
    storage: Any,
    state: AgentState,
    final_answer: str,
    evaluation: dict[str, Any],
    run_id: str,
    session_id: str | None,
    learning_mode: str = "draft",
    learning_threshold: int = 2,
    workflow: str | None = None,
    active_rules: list[str] | None = None,
) -> dict[str, Any]:
    mode = normalize_learning_mode(learning_mode)
    if mode == "off" or storage is None:
        return {"mode": mode, "experience": None, "drafts": []}

    summary = summarize_experience(
        state=state,
        final_answer=final_answer,
        evaluation=evaluation,
        run_id=run_id,
        session_id=session_id,
        workflow=workflow,
        active_rules=active_rules,
    )
    storage.record_experience(summary.to_dict())
    storage.record_event(
        "experience_recorded",
        {
            "run_id": run_id,
            "outcome": summary.outcome,
            "signature": summary.signature,
        },
        session_id=session_id,
        run_id=run_id,
    )

    recurrence_count = storage.count_experiences_by_signature(summary.signature)
    reflection = reflect_experience(
        summary,
        recurrence_count=recurrence_count,
        threshold=max(1, learning_threshold),
    )
    created = []
    for draft_type, candidate in _candidate_items(reflection):
        draft = storage.create_learning_draft(
            draft_type=draft_type,
            title=str(candidate.get("title") or candidate.get("key") or draft_type),
            key=candidate.get("key"),
            payload={**candidate, "reflection": reflection.to_dict()},
            source_run_id=run_id,
        )
        created.append(draft)
        storage.record_event(
            "learning_draft_created",
            {
                "draft_id": draft["id"],
                "draft_type": draft["draft_type"],
                "title": draft["title"],
            },
            session_id=session_id,
            run_id=run_id,
        )

    return {
        "mode": mode,
        "experience": summary.to_dict(),
        "reflection": reflection.to_dict(),
        "drafts": created,
    }


def relevant_skills(storage: Any, goal: str, limit: int = 3) -> list[dict[str, Any]]:
    if storage is None:
        return []
    return match_skills(goal, storage.list_skills(status="active"), limit=limit)


def record_skill_use_results(
    storage: Any,
    skills: list[dict[str, Any]],
    run_id: str,
    session_id: str | None,
    outcome: str,
) -> None:
    if storage is None:
        return
    for skill in skills:
        key = skill.get("key")
        if not key:
            continue
        storage.record_skill_use(
            skill_key=key,
            run_id=run_id,
            session_id=session_id,
            outcome=outcome,
        )
        storage.increment_skill_result(key, success=(outcome == "success"))
        storage.record_event(
            "skill_used",
            {"skill_key": key, "outcome": outcome},
            session_id=session_id,
            run_id=run_id,
        )


def approve_learning_draft(storage: Any, draft_id: int) -> dict[str, Any]:
    draft = storage.get_learning_draft(draft_id)
    if draft is None:
        raise KeyError(f"unknown learning draft: {draft_id}")
    if draft["status"] != "draft":
        raise ValueError(f"learning draft {draft_id} is already {draft['status']}")
    payload = draft.get("payload") or {}
    draft_type = draft.get("draft_type")
    result: dict[str, Any] = {"draft": draft}
    if draft_type == "skill":
        skill = storage.upsert_skill(
            key=payload["key"],
            title=payload["title"],
            description=payload.get("description", ""),
            triggers=payload.get("triggers") or [],
            markdown=payload.get("markdown") or "",
            status="active",
            source_run_ids=payload.get("source_run_ids") or [draft.get("source_run_id")],
        )
        storage.record_event(
            "skill_approved",
            {"skill_key": skill["key"], "draft_id": draft_id},
            run_id=draft.get("source_run_id"),
        )
        result["skill"] = skill
    elif draft_type in {"memory", "anti_pattern"}:
        key = payload.get("key") or f"learning_{draft_id}"
        value = payload.get("value")
        if value is None:
            value = payload
        memory = storage.remember(key, value, source="learning")
        storage.record_event(
            "learning_memory_approved",
            {"key": memory.key, "draft_id": draft_id, "draft_type": draft_type},
            run_id=draft.get("source_run_id"),
        )
        result["memory"] = memory.__dict__
    else:
        raise ValueError(f"unsupported learning draft type: {draft_type}")
    result["draft"] = storage.update_learning_draft_status(draft_id, "approved")
    return result


def reject_learning_draft(storage: Any, draft_id: int) -> dict[str, Any]:
    draft = storage.get_learning_draft(draft_id)
    if draft is None:
        raise KeyError(f"unknown learning draft: {draft_id}")
    updated = storage.update_learning_draft_status(draft_id, "rejected")
    storage.record_event(
        "learning_draft_rejected",
        {"draft_id": draft_id, "draft_type": draft.get("draft_type")},
        run_id=draft.get("source_run_id"),
    )
    return updated


def _candidate_items(reflection: ReflectionRecord) -> list[tuple[str, dict[str, Any]]]:
    items = []
    if reflection.candidate_memory:
        items.append(("memory", reflection.candidate_memory))
    if reflection.candidate_skill:
        items.append(("skill", reflection.candidate_skill))
    if reflection.candidate_anti_pattern:
        items.append(("anti_pattern", reflection.candidate_anti_pattern))
    return items


def _candidate_skill(data: dict[str, Any], tools: list[str]) -> dict[str, Any]:
    goal = str(data.get("goal") or "")
    main_tool = tools[0]
    title = f"Use {main_tool} for similar tasks"
    triggers = _triggers_from_goal(goal, tools)
    key = slugify_skill_key(f"{main_tool} {' '.join(triggers[:3])}", fallback=f"{main_tool}-workflow")
    description = _pattern_sentence(data, tools)
    procedure = [
        "Confirm the user goal matches the trigger terms before applying this skill.",
        f"Use the {main_tool} tool when it is the smallest reliable way to gather the needed evidence.",
        "Summarize only the verified result and note any policy or tool errors plainly.",
    ]
    if len(tools) > 1:
        procedure.insert(2, f"Use related tools in this learned order when needed: {', '.join(tools)}.")
    verification = [
        "Check the stored evaluation and final answer before reusing this skill.",
        "Prefer a fresh tool result over relying on stale observations.",
    ]
    markdown = render_skill_markdown(
        key=key,
        title=title,
        description=description,
        triggers=triggers,
        procedure=procedure,
        verification=verification,
        when_to_use=description,
        status="active",
    )
    return {
        "key": key,
        "title": title,
        "description": description,
        "triggers": triggers,
        "markdown": markdown,
        "source_run_ids": [data.get("run_id")] if data.get("run_id") else [],
    }


def _candidate_memory(data: dict[str, Any]) -> dict[str, Any] | None:
    goal = str(data.get("goal") or "")
    goal_lower = goal.lower()
    markers = ("prefer", "preference", "always use", "default to")
    if not any(marker in goal_lower for marker in markers):
        return None
    secret_markers = ("api key", "apikey", "password", "token", "secret")
    if any(marker in goal_lower for marker in secret_markers):
        return None
    words = [
        word for word in WORD_RE.findall(goal_lower)
        if len(word) >= 4 and word not in STOPWORDS
    ][:5]
    key = slugify_skill_key("preference " + " ".join(words), fallback="preference")
    return {
        "key": key,
        "title": f"Remember preference: {key}",
        "value": {
            "kind": "preference",
            "text": _safe_text(goal, limit=500),
        },
    }


def _pattern_sentence(data: dict[str, Any], tools: list[str]) -> str:
    workflow = data.get("workflow")
    if workflow:
        return f"For {workflow} workflow tasks, {', '.join(tools)} produced a successful answer."
    return f"For similar tasks, {', '.join(tools)} produced a successful answer."


def _triggers_from_goal(goal: str, tools: list[str]) -> list[str]:
    triggers = []
    for tool in tools:
        triggers.append(tool)
    for word in WORD_RE.findall(goal.lower()):
        if len(word) < 4 or word in STOPWORDS:
            continue
        if word not in triggers:
            triggers.append(word)
        if len(triggers) >= 8:
            break
    return triggers or tools or ["task"]


def _experience_signature(goal: str, tools: list[str], workflow: str | None) -> str:
    if workflow:
        return f"workflow:{workflow}"
    if tools:
        return "tools:" + ",".join(tools)
    words = [
        word for word in WORD_RE.findall(goal.lower())
        if len(word) >= 4 and word not in STOPWORDS
    ][:6]
    return "goal:" + ",".join(words)


def _safe_text(value: str, limit: int = 1000) -> str:
    redacted = SECRET_RE.sub("[redacted]", value)
    if len(redacted) <= limit:
        return redacted
    return redacted[: limit - 3] + "..."
