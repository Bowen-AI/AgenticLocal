import re
from dataclasses import dataclass, field
from typing import Any


_WORD_RE = re.compile(r"[a-z0-9][a-z0-9_-]*")


@dataclass
class ProceduralSkill:
    key: str
    title: str
    description: str
    triggers: list[str] = field(default_factory=list)
    markdown: str = ""
    status: str = "active"
    source_run_ids: list[str] = field(default_factory=list)
    success_count: int = 0
    failure_count: int = 0
    created_at_unix: float | None = None
    updated_at_unix: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "title": self.title,
            "description": self.description,
            "triggers": list(self.triggers),
            "markdown": self.markdown,
            "status": self.status,
            "source_run_ids": list(self.source_run_ids),
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "created_at_unix": self.created_at_unix,
            "updated_at_unix": self.updated_at_unix,
        }


def slugify_skill_key(value: str, fallback: str = "skill") -> str:
    words = _WORD_RE.findall(value.lower())
    key = "-".join(words)[:64].strip("-")
    return key or fallback


def parse_skill_markdown(markdown: str) -> dict[str, Any]:
    """Parse the small front-matter subset used by local procedural skills."""
    stripped = markdown.strip()
    if not stripped.startswith("---"):
        return {"markdown": markdown}
    lines = stripped.splitlines()
    metadata: dict[str, Any] = {"triggers": []}
    body_start = 0
    current_list_key: str | None = None
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            body_start = index + 1
            break
        if line.startswith("  - ") and current_list_key:
            metadata.setdefault(current_list_key, []).append(line[4:].strip())
            continue
        current_list_key = None
        if ":" not in line:
            continue
        key, raw_value = line.split(":", 1)
        key = key.strip()
        value = raw_value.strip()
        if value == "":
            current_list_key = key
            metadata[key] = []
        else:
            metadata[key] = value
    metadata["markdown"] = markdown
    metadata["body"] = "\n".join(lines[body_start:]).strip()
    return metadata


def render_skill_markdown(
    key: str,
    title: str,
    description: str,
    triggers: list[str],
    procedure: list[str],
    pitfalls: list[str] | None = None,
    verification: list[str] | None = None,
    when_to_use: str | None = None,
    status: str = "active",
) -> str:
    trigger_lines = "\n".join(f"  - {trigger}" for trigger in triggers)
    procedure_lines = "\n".join(f"{index}. {step}" for index, step in enumerate(procedure, start=1))
    default_pitfalls = ["Watch for stale assumptions and verify the final result."]
    default_verification = ["Run the smallest relevant verification before considering the task done."]
    pitfall_lines = "\n".join(f"- {item}" for item in (pitfalls or default_pitfalls))
    verification_lines = "\n".join(
        f"- {item}" for item in (verification or default_verification)
    )
    when = when_to_use or description
    return (
        "---\n"
        f"key: {key}\n"
        f"title: {title}\n"
        f"description: {description}\n"
        "triggers:\n"
        f"{trigger_lines}\n"
        f"status: {status}\n"
        "---\n\n"
        "## When To Use\n"
        f"{when}\n\n"
        "## Procedure\n"
        f"{procedure_lines}\n\n"
        "## Pitfalls\n"
        f"{pitfall_lines}\n\n"
        "## Verification\n"
        f"{verification_lines}\n"
    )


def skill_from_dict(data: dict[str, Any]) -> ProceduralSkill:
    return ProceduralSkill(
        key=str(data.get("key") or ""),
        title=str(data.get("title") or data.get("key") or ""),
        description=str(data.get("description") or ""),
        triggers=[str(item) for item in data.get("triggers") or []],
        markdown=str(data.get("markdown") or ""),
        status=str(data.get("status") or "active"),
        source_run_ids=[str(item) for item in data.get("source_run_ids") or []],
        success_count=int(data.get("success_count") or 0),
        failure_count=int(data.get("failure_count") or 0),
        created_at_unix=data.get("created_at_unix"),
        updated_at_unix=data.get("updated_at_unix"),
    )


def match_skills(goal: str, skills: list[dict[str, Any]], limit: int = 3) -> list[dict[str, Any]]:
    goal_lower = goal.lower()
    goal_tokens = set(_WORD_RE.findall(goal_lower))
    scored: list[tuple[int, dict[str, Any]]] = []
    for skill in skills:
        if skill.get("status") != "active":
            continue
        triggers = [str(item).lower() for item in skill.get("triggers") or []]
        title = str(skill.get("title") or "").lower()
        description = str(skill.get("description") or "").lower()
        key = str(skill.get("key") or "").lower()
        score = 0
        for trigger in triggers:
            trigger_tokens = set(_WORD_RE.findall(trigger))
            if trigger and trigger in goal_lower:
                score += 4
            elif trigger_tokens and trigger_tokens & goal_tokens:
                score += 2
        metadata_tokens = set(_WORD_RE.findall(f"{key} {title} {description}"))
        score += min(3, len(metadata_tokens & goal_tokens))
        if score > 0:
            scored.append((score, skill))
    scored.sort(
        key=lambda item: (
            -item[0],
            -int(item[1].get("success_count") or 0),
            item[1].get("key") or "",
        )
    )
    return [skill for _score, skill in scored[:limit]]
