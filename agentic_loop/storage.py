import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .memory import MemoryRecord
from .rules import default_rule_metadata, default_workflow_metadata
from .types import AgentStep, Message


def _json_dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=str)


def _json_loads(value: str | None, default: Any = None) -> Any:
    if value is None:
        return default
    return json.loads(value)


class SQLiteStore:
    """Durable local storage for sessions, memory, events, traces, and registries."""

    def __init__(self, path: str | Path = ".agentic/agentic.db"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init_schema()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _init_schema(self) -> None:
        with self._lock, self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    created_at_unix REAL NOT NULL,
                    updated_at_unix REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    name TEXT,
                    tool_call_id TEXT,
                    created_at_unix REAL NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES sessions(session_id)
                );

                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    session_id TEXT,
                    goal TEXT NOT NULL,
                    final_answer TEXT,
                    evaluation_json TEXT,
                    created_at_unix REAL NOT NULL,
                    completed_at_unix REAL
                );

                CREATE TABLE IF NOT EXISTS steps (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    step_index INTEGER NOT NULL,
                    action TEXT NOT NULL,
                    tool_name TEXT,
                    arguments_json TEXT NOT NULL,
                    observation_json TEXT,
                    allowed INTEGER NOT NULL,
                    error TEXT,
                    created_at_unix REAL NOT NULL,
                    FOREIGN KEY(run_id) REFERENCES runs(run_id)
                );

                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    session_id TEXT,
                    run_id TEXT,
                    created_at_unix REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS memory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key TEXT NOT NULL,
                    value_json TEXT NOT NULL,
                    created_at_unix REAL NOT NULL,
                    source TEXT NOT NULL DEFAULT 'tool'
                );

                CREATE TABLE IF NOT EXISTS tool_registry (
                    name TEXT PRIMARY KEY,
                    schema_json TEXT NOT NULL,
                    description TEXT NOT NULL,
                    source TEXT NOT NULL,
                    enabled INTEGER NOT NULL,
                    risk_level TEXT NOT NULL,
                    ui_component_hint TEXT,
                    updated_at_unix REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS ui_registry (
                    event_type TEXT PRIMARY KEY,
                    component TEXT NOT NULL,
                    description TEXT NOT NULL,
                    enabled INTEGER NOT NULL,
                    updated_at_unix REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS rule_registry (
                    key TEXT PRIMARY KEY,
                    label TEXT NOT NULL,
                    description TEXT NOT NULL,
                    category TEXT NOT NULL,
                    prompt_text TEXT NOT NULL,
                    policy_json TEXT NOT NULL,
                    default_enabled INTEGER NOT NULL,
                    priority INTEGER NOT NULL,
                    updated_at_unix REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS rule_settings (
                    scope_type TEXT NOT NULL,
                    scope_id TEXT NOT NULL DEFAULT '',
                    rule_key TEXT NOT NULL,
                    enabled INTEGER NOT NULL,
                    updated_at_unix REAL NOT NULL,
                    PRIMARY KEY(scope_type, scope_id, rule_key)
                );

                CREATE TABLE IF NOT EXISTS workflow_registry (
                    key TEXT PRIMARY KEY,
                    slash_command TEXT NOT NULL,
                    description TEXT NOT NULL,
                    rule_keys_json TEXT NOT NULL,
                    max_steps_override INTEGER,
                    required_tools_json TEXT NOT NULL,
                    prompt_prefix TEXT NOT NULL,
                    enabled INTEGER NOT NULL,
                    updated_at_unix REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS experiences (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL UNIQUE,
                    session_id TEXT,
                    goal TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    signature TEXT NOT NULL,
                    summary_json TEXT NOT NULL,
                    created_at_unix REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS learning_drafts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    draft_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    title TEXT NOT NULL,
                    key TEXT,
                    payload_json TEXT NOT NULL,
                    source_run_id TEXT,
                    created_at_unix REAL NOT NULL,
                    updated_at_unix REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS skills (
                    key TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    triggers_json TEXT NOT NULL,
                    markdown TEXT NOT NULL,
                    status TEXT NOT NULL,
                    source_run_ids_json TEXT NOT NULL,
                    success_count INTEGER NOT NULL DEFAULT 0,
                    failure_count INTEGER NOT NULL DEFAULT 0,
                    created_at_unix REAL NOT NULL,
                    updated_at_unix REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS skill_uses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    skill_key TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    session_id TEXT,
                    outcome TEXT NOT NULL,
                    created_at_unix REAL NOT NULL,
                    FOREIGN KEY(skill_key) REFERENCES skills(key)
                );
                """
            )

    def ensure_session(self, session_id: str) -> None:
        now = time.time()
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO sessions(session_id, created_at_unix, updated_at_unix)
                VALUES(?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET updated_at_unix=excluded.updated_at_unix
                """,
                (session_id, now, now),
            )

    def session_exists(self, session_id: str) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        return row is not None

    def list_sessions(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT session_id, created_at_unix, updated_at_unix
                FROM sessions
                ORDER BY updated_at_unix DESC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def append_message(self, session_id: str, message: Message) -> None:
        self.ensure_session(session_id)
        now = time.time()
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO messages(
                    session_id, role, content, name, tool_call_id, created_at_unix
                )
                VALUES(?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    message.role,
                    message.content,
                    message.name,
                    message.tool_call_id,
                    now,
                ),
            )
            connection.execute(
                "UPDATE sessions SET updated_at_unix = ? WHERE session_id = ?",
                (now, session_id),
            )

    def load_messages(self, session_id: str) -> list[Message]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT role, content, name, tool_call_id
                FROM messages
                WHERE session_id = ?
                ORDER BY id ASC
                """,
                (session_id,),
            ).fetchall()
        return [
            Message(
                role=row["role"],
                content=row["content"],
                name=row["name"],
                tool_call_id=row["tool_call_id"],
            )
            for row in rows
        ]

    def start_run(self, run_id: str, goal: str, session_id: str | None = None) -> None:
        now = time.time()
        if session_id:
            self.ensure_session(session_id)
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO runs(run_id, session_id, goal, created_at_unix)
                VALUES(?, ?, ?, ?)
                """,
                (run_id, session_id, goal, now),
            )

    def save_run_result(
        self,
        run_id: str,
        session_id: str | None,
        goal: str,
        final_answer: str,
        evaluation: dict[str, Any],
        steps: list[AgentStep],
    ) -> None:
        now = time.time()
        self.start_run(run_id, goal, session_id)
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE runs
                SET final_answer = ?, evaluation_json = ?, completed_at_unix = ?
                WHERE run_id = ?
                """,
                (final_answer, _json_dumps(evaluation), now, run_id),
            )
            connection.execute("DELETE FROM steps WHERE run_id = ?", (run_id,))
            connection.executemany(
                """
                INSERT INTO steps(
                    run_id, step_index, action, tool_name, arguments_json,
                    observation_json, allowed, error, created_at_unix
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        run_id,
                        step.index,
                        step.action,
                        step.tool_name,
                        _json_dumps(step.arguments),
                        _json_dumps(step.observation),
                        1 if step.allowed else 0,
                        step.error,
                        now,
                    )
                    for step in steps
                ],
            )

    def record_event(
        self,
        event_type: str,
        payload: dict[str, Any],
        session_id: str | None = None,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        now = time.time()
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO events(event_type, payload_json, session_id, run_id, created_at_unix)
                VALUES(?, ?, ?, ?, ?)
                """,
                (event_type, _json_dumps(payload), session_id, run_id, now),
            )
            event_id = cursor.lastrowid
        return {
            "id": event_id,
            "event_type": event_type,
            "payload": payload,
            "session_id": session_id,
            "run_id": run_id,
            "created_at_unix": now,
        }

    def events_after(
        self,
        session_id: str | None = None,
        after_id: int = 0,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        params: list[Any] = [after_id]
        where = "id > ?"
        if session_id is not None:
            where += " AND session_id = ?"
            params.append(session_id)
        params.append(limit)
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT id, event_type, payload_json, session_id, run_id, created_at_unix
                FROM events
                WHERE {where}
                ORDER BY id ASC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [self._event_from_row(row) for row in rows]

    def _event_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "event_type": row["event_type"],
            "payload": _json_loads(row["payload_json"], {}),
            "session_id": row["session_id"],
            "run_id": row["run_id"],
            "created_at_unix": row["created_at_unix"],
        }

    def remember(self, key: str, value: Any, source: str = "tool") -> MemoryRecord:
        record = MemoryRecord(key=key, value=value, created_at_unix=time.time())
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO memory(key, value_json, created_at_unix, source)
                VALUES(?, ?, ?, ?)
                """,
                (record.key, _json_dumps(record.value), record.created_at_unix, source),
            )
        return record

    def all(self) -> list[MemoryRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT key, value_json, created_at_unix
                FROM memory
                ORDER BY id ASC
                """
            ).fetchall()
        return [
            MemoryRecord(
                key=row["key"],
                value=_json_loads(row["value_json"]),
                created_at_unix=row["created_at_unix"],
            )
            for row in rows
        ]

    def latest(self, key: str) -> MemoryRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT key, value_json, created_at_unix
                FROM memory
                WHERE key = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (key,),
            ).fetchone()
        if row is None:
            return None
        return MemoryRecord(
            key=row["key"],
            value=_json_loads(row["value_json"]),
            created_at_unix=row["created_at_unix"],
        )

    def search(self, query: str, limit: int = 5) -> list[MemoryRecord]:
        query_lower = query.lower()
        matches = []
        for record in self.all():
            haystack = f"{record.key} {_json_dumps(record.value)}".lower()
            if query_lower in haystack:
                matches.append(record)
        return matches[-limit:]

    def record_experience(self, summary: dict[str, Any]) -> dict[str, Any]:
        now = time.time()
        run_id = str(summary["run_id"])
        session_id = summary.get("session_id")
        goal = str(summary.get("goal") or "")
        outcome = str(summary.get("outcome") or "unknown")
        signature = str(summary.get("signature") or "")
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO experiences(
                    run_id, session_id, goal, outcome, signature,
                    summary_json, created_at_unix
                )
                VALUES(?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    session_id = excluded.session_id,
                    goal = excluded.goal,
                    outcome = excluded.outcome,
                    signature = excluded.signature,
                    summary_json = excluded.summary_json
                """,
                (run_id, session_id, goal, outcome, signature, _json_dumps(summary), now),
            )
        stored = dict(summary)
        stored["created_at_unix"] = now
        return stored

    def list_experiences(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT run_id, session_id, goal, outcome, signature,
                       summary_json, created_at_unix
                FROM experiences
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [self._experience_from_row(row) for row in rows]

    def count_experiences_by_signature(self, signature: str) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM experiences WHERE signature = ?",
                (signature,),
            ).fetchone()
        return int(row["count"] if row is not None else 0)

    def _experience_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        summary = _json_loads(row["summary_json"], {})
        if not isinstance(summary, dict):
            summary = {}
        summary.update(
            {
                "run_id": row["run_id"],
                "session_id": row["session_id"],
                "goal": row["goal"],
                "outcome": row["outcome"],
                "signature": row["signature"],
                "created_at_unix": row["created_at_unix"],
            }
        )
        return summary

    def create_learning_draft(
        self,
        draft_type: str,
        title: str,
        key: str | None,
        payload: dict[str, Any],
        source_run_id: str | None = None,
    ) -> dict[str, Any]:
        now = time.time()
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO learning_drafts(
                    draft_type, status, title, key, payload_json,
                    source_run_id, created_at_unix, updated_at_unix
                )
                VALUES(?, 'draft', ?, ?, ?, ?, ?, ?)
                """,
                (
                    draft_type,
                    title,
                    key,
                    _json_dumps(payload),
                    source_run_id,
                    now,
                    now,
                ),
            )
            draft_id = cursor.lastrowid
        return {
            "id": draft_id,
            "draft_type": draft_type,
            "status": "draft",
            "title": title,
            "key": key,
            "payload": payload,
            "source_run_id": source_run_id,
            "created_at_unix": now,
            "updated_at_unix": now,
        }

    def list_learning_drafts(
        self,
        status: str | None = "draft",
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        params: list[Any] = []
        where = ""
        if status is not None:
            where = "WHERE status = ?"
            params.append(status)
        params.append(limit)
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT id, draft_type, status, title, key, payload_json,
                       source_run_id, created_at_unix, updated_at_unix
                FROM learning_drafts
                {where}
                ORDER BY id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [self._learning_draft_from_row(row) for row in rows]

    def get_learning_draft(self, draft_id: int) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, draft_type, status, title, key, payload_json,
                       source_run_id, created_at_unix, updated_at_unix
                FROM learning_drafts
                WHERE id = ?
                """,
                (draft_id,),
            ).fetchone()
        return self._learning_draft_from_row(row) if row is not None else None

    def update_learning_draft_status(self, draft_id: int, status: str) -> dict[str, Any]:
        now = time.time()
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE learning_drafts
                SET status = ?, updated_at_unix = ?
                WHERE id = ?
                """,
                (status, now, draft_id),
            )
        updated = self.get_learning_draft(draft_id)
        if updated is None:
            raise KeyError(f"unknown learning draft: {draft_id}")
        return updated

    def _learning_draft_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "draft_type": row["draft_type"],
            "status": row["status"],
            "title": row["title"],
            "key": row["key"],
            "payload": _json_loads(row["payload_json"], {}),
            "source_run_id": row["source_run_id"],
            "created_at_unix": row["created_at_unix"],
            "updated_at_unix": row["updated_at_unix"],
        }

    def upsert_skill(
        self,
        key: str,
        title: str,
        description: str,
        triggers: list[str],
        markdown: str,
        status: str = "active",
        source_run_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        now = time.time()
        existing = self.get_skill(key)
        created_at = existing["created_at_unix"] if existing else now
        merged_source_ids = []
        for source_id in (existing or {}).get("source_run_ids", []) + (source_run_ids or []):
            if source_id and source_id not in merged_source_ids:
                merged_source_ids.append(source_id)
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO skills(
                    key, title, description, triggers_json, markdown, status,
                    source_run_ids_json, success_count, failure_count,
                    created_at_unix, updated_at_unix
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    title = excluded.title,
                    description = excluded.description,
                    triggers_json = excluded.triggers_json,
                    markdown = excluded.markdown,
                    status = excluded.status,
                    source_run_ids_json = excluded.source_run_ids_json,
                    updated_at_unix = excluded.updated_at_unix
                """,
                (
                    key,
                    title,
                    description,
                    _json_dumps(triggers),
                    markdown,
                    status,
                    _json_dumps(merged_source_ids),
                    int((existing or {}).get("success_count") or 0),
                    int((existing or {}).get("failure_count") or 0),
                    created_at,
                    now,
                ),
            )
        return self.get_skill(key) or {}

    def list_skills(
        self,
        status: str | None = "active",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        params: list[Any] = []
        where = ""
        if status is not None:
            where = "WHERE status = ?"
            params.append(status)
        params.append(limit)
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT key, title, description, triggers_json, markdown, status,
                       source_run_ids_json, success_count, failure_count,
                       created_at_unix, updated_at_unix
                FROM skills
                {where}
                ORDER BY updated_at_unix DESC, key ASC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [self._skill_from_row(row) for row in rows]

    def get_skill(self, key: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT key, title, description, triggers_json, markdown, status,
                       source_run_ids_json, success_count, failure_count,
                       created_at_unix, updated_at_unix
                FROM skills
                WHERE key = ?
                """,
                (key,),
            ).fetchone()
        return self._skill_from_row(row) if row is not None else None

    def archive_skill(self, key: str) -> dict[str, Any]:
        now = time.time()
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE skills
                SET status = 'archived', updated_at_unix = ?
                WHERE key = ?
                """,
                (now, key),
            )
        archived = self.get_skill(key)
        if archived is None:
            raise KeyError(f"unknown skill: {key}")
        return archived

    def record_skill_use(
        self,
        skill_key: str,
        run_id: str,
        session_id: str | None,
        outcome: str,
    ) -> dict[str, Any]:
        now = time.time()
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO skill_uses(skill_key, run_id, session_id, outcome, created_at_unix)
                VALUES(?, ?, ?, ?, ?)
                """,
                (skill_key, run_id, session_id, outcome, now),
            )
            use_id = cursor.lastrowid
        return {
            "id": use_id,
            "skill_key": skill_key,
            "run_id": run_id,
            "session_id": session_id,
            "outcome": outcome,
            "created_at_unix": now,
        }

    def increment_skill_result(self, key: str, success: bool) -> dict[str, Any]:
        now = time.time()
        column = "success_count" if success else "failure_count"
        with self._lock, self._connect() as connection:
            connection.execute(
                f"""
                UPDATE skills
                SET {column} = {column} + 1, updated_at_unix = ?
                WHERE key = ?
                """,
                (now, key),
            )
        updated = self.get_skill(key)
        if updated is None:
            raise KeyError(f"unknown skill: {key}")
        return updated

    def list_skill_uses(self, skill_key: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        params: list[Any] = []
        where = ""
        if skill_key is not None:
            where = "WHERE skill_key = ?"
            params.append(skill_key)
        params.append(limit)
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT id, skill_key, run_id, session_id, outcome, created_at_unix
                FROM skill_uses
                {where}
                ORDER BY id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    def _skill_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "key": row["key"],
            "title": row["title"],
            "description": row["description"],
            "triggers": _json_loads(row["triggers_json"], []),
            "markdown": row["markdown"],
            "status": row["status"],
            "source_run_ids": _json_loads(row["source_run_ids_json"], []),
            "success_count": row["success_count"],
            "failure_count": row["failure_count"],
            "created_at_unix": row["created_at_unix"],
            "updated_at_unix": row["updated_at_unix"],
        }

    def seed_tool_registry(self, metadata: list[dict[str, Any]]) -> None:
        now = time.time()
        with self._lock, self._connect() as connection:
            connection.executemany(
                """
                INSERT INTO tool_registry(
                    name, schema_json, description, source, enabled,
                    risk_level, ui_component_hint, updated_at_unix
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    schema_json = excluded.schema_json,
                    description = excluded.description,
                    source = excluded.source,
                    enabled = excluded.enabled,
                    risk_level = excluded.risk_level,
                    ui_component_hint = excluded.ui_component_hint,
                    updated_at_unix = excluded.updated_at_unix
                """,
                [
                    (
                        item["name"],
                        _json_dumps(item["schema"]),
                        item.get("description", ""),
                        item.get("source", "local"),
                        1 if item.get("enabled", True) else 0,
                        item.get("risk_level", "low"),
                        item.get("ui_component_hint"),
                        now,
                    )
                    for item in metadata
                ],
            )

    def list_tool_registry(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT name, schema_json, description, source, enabled,
                       risk_level, ui_component_hint, updated_at_unix
                FROM tool_registry
                ORDER BY name ASC
                """
            ).fetchall()
        return [
            {
                "name": row["name"],
                "schema": _json_loads(row["schema_json"], {}),
                "description": row["description"],
                "source": row["source"],
                "enabled": bool(row["enabled"]),
                "risk_level": row["risk_level"],
                "ui_component_hint": row["ui_component_hint"],
                "updated_at_unix": row["updated_at_unix"],
            }
            for row in rows
        ]

    def seed_default_ui_registry(self) -> None:
        defaults = [
            ("run_started", "status_banner", "Show the active run goal."),
            ("model_requested", "tool_timeline_row", "Show model planning turns."),
            ("tool_requested", "tool_timeline_row", "Show requested tool calls."),
            ("approval_required", "approval_modal", "Ask for human review before proceeding."),
            ("tool_result", "tool_result_panel", "Render successful tool outputs."),
            ("tool_error", "error_panel", "Render tool execution errors."),
            ("state_delta", "state_panel", "Render compact working-state changes."),
            ("memory_written", "memory_view", "Render long-term memory writes."),
            ("experience_recorded", "tool_timeline_row", "Show when a completed run was summarized."),
            ("learning_draft_created", "tool_timeline_row", "Show proposed learning artifacts."),
            ("skill_approved", "memory_view", "Render approved procedural skills."),
            ("skill_used", "tool_timeline_row", "Show procedural skills reused for a run."),
            ("final_answer", "chat_message", "Render the assistant response."),
            ("list_files", "file_browser", "Render workspace file listings."),
            ("inspect_csv", "table_preview", "Render dataset previews and summaries."),
        ]
        now = time.time()
        with self._lock, self._connect() as connection:
            connection.executemany(
                """
                INSERT INTO ui_registry(
                    event_type, component, description, enabled, updated_at_unix
                )
                VALUES(?, ?, ?, ?, ?)
                ON CONFLICT(event_type) DO UPDATE SET
                    component = excluded.component,
                    description = excluded.description,
                    enabled = excluded.enabled,
                    updated_at_unix = excluded.updated_at_unix
                """,
                [
                    (event_type, component, description, 1, now)
                    for event_type, component, description in defaults
                ],
            )

    def list_ui_registry(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT event_type, component, description, enabled, updated_at_unix
                FROM ui_registry
                ORDER BY event_type ASC
                """
            ).fetchall()
        return [
            {
                "event_type": row["event_type"],
                "component": row["component"],
                "description": row["description"],
                "enabled": bool(row["enabled"]),
                "updated_at_unix": row["updated_at_unix"],
            }
            for row in rows
        ]

    def seed_default_rule_registry(self) -> None:
        self.seed_rule_registry(default_rule_metadata())

    def seed_rule_registry(self, metadata: list[dict[str, Any]]) -> None:
        now = time.time()
        with self._lock, self._connect() as connection:
            connection.executemany(
                """
                INSERT INTO rule_registry(
                    key, label, description, category, prompt_text, policy_json,
                    default_enabled, priority, updated_at_unix
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    label = excluded.label,
                    description = excluded.description,
                    category = excluded.category,
                    prompt_text = excluded.prompt_text,
                    policy_json = excluded.policy_json,
                    default_enabled = excluded.default_enabled,
                    priority = excluded.priority,
                    updated_at_unix = excluded.updated_at_unix
                """,
                [
                    (
                        item["key"],
                        item.get("label", item["key"]),
                        item.get("description", ""),
                        item.get("category", "general"),
                        item.get("prompt_text", ""),
                        _json_dumps(item.get("policy") or {}),
                        1 if item.get("default_enabled", False) else 0,
                        int(item.get("priority", 100)),
                        now,
                    )
                    for item in metadata
                ],
            )

    def list_rule_registry(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT key, label, description, category, prompt_text, policy_json,
                       default_enabled, priority, updated_at_unix
                FROM rule_registry
                ORDER BY priority ASC, key ASC
                """
            ).fetchall()
        return [
            {
                "key": row["key"],
                "label": row["label"],
                "description": row["description"],
                "category": row["category"],
                "prompt_text": row["prompt_text"],
                "policy": _json_loads(row["policy_json"], {}),
                "default_enabled": bool(row["default_enabled"]),
                "priority": row["priority"],
                "updated_at_unix": row["updated_at_unix"],
            }
            for row in rows
        ]

    def set_rule_enabled(
        self,
        rule_key: str,
        enabled: bool,
        scope_type: str = "global",
        scope_id: str | None = None,
    ) -> None:
        if scope_type not in {"global", "session", "run"}:
            raise ValueError(f"unknown rule scope: {scope_type}")
        if scope_type != "global" and not scope_id:
            raise ValueError(f"{scope_type} rule settings require scope_id")
        normalized_scope_id = "" if scope_type == "global" else (scope_id or "")
        now = time.time()
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO rule_settings(scope_type, scope_id, rule_key, enabled, updated_at_unix)
                VALUES(?, ?, ?, ?, ?)
                ON CONFLICT(scope_type, scope_id, rule_key) DO UPDATE SET
                    enabled = excluded.enabled,
                    updated_at_unix = excluded.updated_at_unix
                """,
                (
                    scope_type,
                    normalized_scope_id,
                    rule_key,
                    1 if enabled else 0,
                    now,
                ),
            )

    def list_rule_settings(
        self,
        scope_type: str | None = None,
        scope_id: str | None = None,
    ) -> list[dict[str, Any]]:
        params: list[Any] = []
        where = []
        if scope_type is not None:
            where.append("scope_type = ?")
            params.append(scope_type)
        if scope_id is not None:
            where.append("scope_id = ?")
            params.append(scope_id)
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT scope_type, scope_id, rule_key, enabled, updated_at_unix
                FROM rule_settings
                {clause}
                ORDER BY scope_type ASC, scope_id ASC, rule_key ASC
                """,
                params,
            ).fetchall()
        return [
            {
                "scope_type": row["scope_type"],
                "scope_id": row["scope_id"],
                "rule_key": row["rule_key"],
                "enabled": bool(row["enabled"]),
                "updated_at_unix": row["updated_at_unix"],
            }
            for row in rows
        ]

    def seed_default_workflow_registry(self) -> None:
        self.seed_workflow_registry(default_workflow_metadata())

    def seed_workflow_registry(self, metadata: list[dict[str, Any]]) -> None:
        now = time.time()
        with self._lock, self._connect() as connection:
            connection.executemany(
                """
                INSERT INTO workflow_registry(
                    key, slash_command, description, rule_keys_json,
                    max_steps_override, required_tools_json, prompt_prefix,
                    enabled, updated_at_unix
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    slash_command = excluded.slash_command,
                    description = excluded.description,
                    rule_keys_json = excluded.rule_keys_json,
                    max_steps_override = excluded.max_steps_override,
                    required_tools_json = excluded.required_tools_json,
                    prompt_prefix = excluded.prompt_prefix,
                    enabled = excluded.enabled,
                    updated_at_unix = excluded.updated_at_unix
                """,
                [
                    (
                        item["key"],
                        item.get("command") or f"/{item['key']}",
                        item.get("description", ""),
                        _json_dumps(item.get("rule_keys") or []),
                        item.get("max_steps_override"),
                        _json_dumps(item.get("required_tools") or []),
                        item.get("prompt_prefix", ""),
                        1 if item.get("enabled", True) else 0,
                        now,
                    )
                    for item in metadata
                ],
            )

    def list_workflow_registry(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT key, slash_command, description, rule_keys_json,
                       max_steps_override, required_tools_json, prompt_prefix,
                       enabled, updated_at_unix
                FROM workflow_registry
                ORDER BY key ASC
                """
            ).fetchall()
        return [
            {
                "key": row["key"],
                "command": row["slash_command"],
                "description": row["description"],
                "rule_keys": _json_loads(row["rule_keys_json"], []),
                "max_steps_override": row["max_steps_override"],
                "required_tools": _json_loads(row["required_tools_json"], []),
                "prompt_prefix": row["prompt_prefix"],
                "enabled": bool(row["enabled"]),
                "updated_at_unix": row["updated_at_unix"],
            }
            for row in rows
        ]
