import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

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

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        return connection

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

    def remember(self, key: str, value: Any) -> MemoryRecord:
        record = MemoryRecord(key=key, value=value, created_at_unix=time.time())
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO memory(key, value_json, created_at_unix, source)
                VALUES(?, ?, ?, ?)
                """,
                (record.key, _json_dumps(record.value), record.created_at_unix, "tool"),
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
                [(event_type, component, description, 1, now) for event_type, component, description in defaults],
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
