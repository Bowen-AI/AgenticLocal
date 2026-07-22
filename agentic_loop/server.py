import argparse
import json
import os
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from .factory import create_controller
from .learning import LEARNING_MODES, approve_learning_draft, reject_learning_draft
from .model_selection import (
    DEFAULT_INTERACTIVE_MODEL,
    DEFAULT_INTERACTIVE_PROVIDER,
    DEFAULT_OLLAMA_HOST,
    ModelSelection,
    provider_registry,
)
from .ollama_runtime import ensure_ollama_model_available
from .rules import RuleResolver
from .session import AgentSession
from .storage import SQLiteStore
from .tools import ToolRegistry, create_default_tools
from .types import Message
from .version import __version__
from .voice import voice_page_html
from .voice_adapters import (
    DEFAULT_GEMINI_LIVE_MODEL,
    GeminiLiveTokenClient,
    GeminiLiveTokenError,
)


VOICE_PROVIDERS = {"auto", "browser", "gemini-live"}


def format_sse_events(events: list[dict[str, Any]]) -> str:
    chunks = []
    for event in events:
        chunks.append(
            "\n".join(
                [
                    f"id: {event['id']}",
                    f"event: {event['event_type']}",
                    f"data: {json.dumps(event, sort_keys=True)}",
                    "",
                ]
            )
        )
    return "\n".join(chunks) + ("\n" if chunks else "")


class AgentServerApp:
    def __init__(
        self,
        workspace: str = "sample_workspace",
        memory_path: str | None = None,
        trace_path: str | None = None,
        db_path: str | None = ".agentic/agentic.db",
        max_steps: int = 8,
        provider: str = "rule",
        model_name: str | None = None,
        ollama_host: str = "http://127.0.0.1:11434",
        api_base: str | None = None,
        api_key: str | None = None,
        read_roots: list[str] | None = None,
        write_roots: list[str] | None = None,
        approval_required_roots: list[str] | None = None,
        storage: SQLiteStore | None = None,
        enable_network_tools: bool = False,
        tools_factory: Callable[[], ToolRegistry] | None = None,
        voice_provider: str = "auto",
        voice_model: str | None = None,
        gemini_api_key: str | None = None,
        voice_token_client: GeminiLiveTokenClient | None = None,
        learning_mode: str = "draft",
        learning_threshold: int = 2,
        system_prompt: str | None = None,
    ):
        if voice_provider not in VOICE_PROVIDERS:
            allowed = ", ".join(sorted(VOICE_PROVIDERS))
            raise ValueError(f"voice_provider must be one of: {allowed}")
        if learning_mode not in LEARNING_MODES:
            allowed = ", ".join(sorted(LEARNING_MODES))
            raise ValueError(f"learning_mode must be one of: {allowed}")
        self.workspace = workspace
        self.memory_path = memory_path
        self.trace_path = trace_path
        self.db_path = db_path
        self.max_steps = max_steps
        self.default_model_selection = ModelSelection.from_values(
            provider=provider,
            model_name=model_name,
            ollama_host=ollama_host,
            api_base=api_base,
            api_key=api_key,
        )
        self.read_roots = read_roots
        self.write_roots = write_roots
        self.approval_required_roots = approval_required_roots
        self.enable_network_tools = enable_network_tools
        self.voice_provider = voice_provider
        self.voice_model = voice_model or DEFAULT_GEMINI_LIVE_MODEL
        self.learning_mode = learning_mode
        self.learning_threshold = learning_threshold
        self.system_prompt = system_prompt
        self.gemini_api_key = (
            gemini_api_key
            or os.environ.get("GEMINI_API_KEY")
            or os.environ.get("GOOGLE_API_KEY")
        )
        self.voice_token_client = voice_token_client or GeminiLiveTokenClient(
            api_key=self.gemini_api_key,
            model=self.voice_model,
        )
        self.tools_factory = tools_factory or (
            lambda: create_default_tools(enable_network=enable_network_tools)
        )
        self.storage = storage or SQLiteStore(db_path or ".agentic/agentic.db")
        self.sessions: dict[str, AgentSession] = {}
        self.session_workflows: dict[str, str] = {}
        self.session_model_selections: dict[str, ModelSelection] = {}
        self.storage.seed_tool_registry(self._create_tools().metadata())
        self.storage.seed_default_ui_registry()
        self.storage.seed_default_rule_registry()
        self.storage.seed_default_workflow_registry()
        self.rule_resolver = RuleResolver(self.storage)

    def create_session(self, model_selection: ModelSelection | None = None) -> str:
        session_id = uuid.uuid4().hex
        self.storage.ensure_session(session_id)
        selected_model = model_selection or self.default_model_selection
        self.session_model_selections[session_id] = selected_model
        self.sessions[session_id] = self._make_session(session_id, [], selected_model)
        return session_id

    def get_session(
        self,
        session_id: str | None,
        model_selection: ModelSelection | None = None,
    ) -> tuple[str, AgentSession]:
        if not session_id:
            session_id = self.create_session(model_selection)
        if session_id not in self.sessions:
            if not self.storage.session_exists(session_id):
                raise KeyError(f"unknown session_id: {session_id}")
            selected_model = (
                model_selection
                or self.session_model_selections.get(session_id)
                or self.default_model_selection
            )
            self.session_model_selections[session_id] = selected_model
            self.sessions[session_id] = self._make_session(
                session_id,
                self.storage.load_messages(session_id),
                selected_model,
            )
        elif model_selection is not None:
            self.session_model_selections[session_id] = model_selection
            self.sessions[session_id] = self._make_session(
                session_id,
                self.sessions[session_id].history,
                model_selection,
            )
        return session_id, self.sessions[session_id]

    def _make_controller(self, model_selection: ModelSelection | None = None):
        selected_model = model_selection or self.default_model_selection
        return create_controller(
            workspace=self.workspace,
            memory_path=self.memory_path,
            trace_path=self.trace_path,
            db_path=self.db_path,
            max_steps=self.max_steps,
            provider=selected_model.provider,
            model_name=selected_model.model_name,
            ollama_host=selected_model.ollama_host or "http://127.0.0.1:11434",
            api_base=selected_model.api_base,
            api_key=selected_model.api_key,
            read_roots=self.read_roots,
            write_roots=self.write_roots,
            approval_required_roots=self.approval_required_roots,
            storage=self.storage,
            enable_network_tools=self.enable_network_tools,
            tools=self._create_tools(),
            learning_mode=self.learning_mode,
            learning_threshold=self.learning_threshold,
            system_prompt=self.system_prompt,
        )

    def _make_session(
        self,
        session_id: str,
        history: list[Message],
        model_selection: ModelSelection | None = None,
    ) -> AgentSession:
        return AgentSession(
            self._make_controller(model_selection),
            history=history,
            session_id=session_id,
            storage=self.storage,
        )

    def run_once(
        self,
        message: str,
        enabled_rule_keys: list[str] | None = None,
        disabled_rule_keys: list[str] | None = None,
        workflow_key: str | None = None,
        model_selection: ModelSelection | None = None,
    ) -> dict[str, Any]:
        selected_model = model_selection or self.default_model_selection
        controller = self._make_controller(selected_model)
        result = controller.run(
            message,
            enabled_rule_keys=enabled_rule_keys,
            disabled_rule_keys=disabled_rule_keys,
            workflow_key=workflow_key,
        )
        return serialize_result(result, selected_model)

    def chat(
        self,
        message: str,
        session_id: str | None = None,
        enabled_rule_keys: list[str] | None = None,
        disabled_rule_keys: list[str] | None = None,
        workflow_key: str | None = None,
        model_selection: ModelSelection | None = None,
        cancel_event=None,
        on_event=None,
        max_steps: int | None = None,
        approval_callback=None,
    ) -> dict[str, Any]:
        session_id, session = self.get_session(session_id, model_selection)
        selected_model = self.session_model_selections.get(session_id, self.default_model_selection)
        result = session.ask(
            message,
            enabled_rule_keys=enabled_rule_keys,
            disabled_rule_keys=disabled_rule_keys,
            workflow_key=workflow_key or self.session_workflows.get(session_id),
            cancel_event=cancel_event,
            on_event=on_event,
            max_steps=max_steps,
            approval_callback=approval_callback,
        )
        payload = serialize_result(result, selected_model)
        payload["session_id"] = session_id
        payload["transcript"] = session.transcript()
        return payload

    def events(self, session_id: str | None = None, after_id: int = 0) -> list[dict[str, Any]]:
        return self.storage.events_after(session_id=session_id, after_id=after_id)

    def list_sessions(self) -> list[dict[str, Any]]:
        return self.storage.list_sessions()

    def memory_records(self) -> list[dict[str, Any]]:
        return [record.__dict__ for record in self.storage.all()]

    def learning_drafts(self, status: str | None = "draft") -> list[dict[str, Any]]:
        return self.storage.list_learning_drafts(status=status)

    def approve_learning_draft(self, draft_id: int) -> dict[str, Any]:
        return approve_learning_draft(self.storage, draft_id)

    def reject_learning_draft(self, draft_id: int) -> dict[str, Any]:
        return reject_learning_draft(self.storage, draft_id)

    def skills(self, status: str | None = "active") -> list[dict[str, Any]]:
        return self.storage.list_skills(status=status)

    def skill(self, key: str) -> dict[str, Any]:
        item = self.storage.get_skill(key)
        if item is None:
            raise KeyError(f"unknown skill: {key}")
        return item

    def archive_skill(self, key: str) -> dict[str, Any]:
        archived = self.storage.archive_skill(key)
        self.storage.record_event("skill_archived", {"skill_key": key})
        return archived

    def tool_registry(self) -> list[dict[str, Any]]:
        return self.storage.list_tool_registry()

    def ui_registry(self) -> list[dict[str, Any]]:
        return self.storage.list_ui_registry()

    def rule_registry(self, session_id: str | None = None) -> list[dict[str, Any]]:
        return self.rule_resolver.rules_with_state(session_id=session_id)

    def workflow_registry(self) -> list[dict[str, Any]]:
        return [workflow.to_dict() for workflow in self.rule_resolver.workflows()]

    def _create_tools(self) -> ToolRegistry:
        return self.tools_factory()

    def model_registry(self, session_id: str | None = None) -> dict[str, Any]:
        current = (
            self.session_model_selections.get(session_id)
            if session_id
            else self.default_model_selection
        )
        return {
            "providers": provider_registry(),
            "default": self.default_model_selection.to_dict(),
            "current": (current or self.default_model_selection).to_dict(),
        }

    def model_selection_from_payload(
        self,
        payload: dict[str, Any] | None,
        session_id: str | None = None,
    ) -> ModelSelection:
        fallback = (
            self.session_model_selections.get(session_id)
            if session_id
            else self.default_model_selection
        ) or self.default_model_selection
        return ModelSelection.from_payload(payload or {}, fallback=fallback)

    def select_model(
        self,
        model_selection: ModelSelection,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        if session_id is None:
            session_id = self.create_session(model_selection)
        else:
            self.get_session(session_id, model_selection)
        return {
            "session_id": session_id,
            "model": model_selection.to_dict(),
        }

    def toggle_rule(
        self,
        rule_key: str,
        enabled: bool,
        scope_type: str = "global",
        session_id: str | None = None,
    ) -> dict[str, Any]:
        known = {rule["key"] for rule in self.storage.list_rule_registry()}
        if rule_key not in known:
            raise KeyError(f"unknown rule: {rule_key}")
        self.storage.set_rule_enabled(
            rule_key,
            enabled,
            scope_type=scope_type,
            scope_id=session_id,
        )
        return {
            "rule": rule_key,
            "enabled": enabled,
            "scope_type": scope_type,
            "session_id": session_id,
            "rules": self.rule_registry(session_id=session_id),
        }

    def start_workflow(
        self,
        workflow_key: str,
        session_id: str | None = None,
        message: str | None = None,
    ) -> dict[str, Any]:
        workflow = self.rule_resolver.workflow(workflow_key)
        if workflow is None:
            raise KeyError(f"unknown workflow: {workflow_key}")
        if message:
            return self.chat(message, session_id=session_id, workflow_key=workflow.key)
        if not workflow.enabled:
            raise ValueError(f"Workflow {workflow.command} is disabled.")
        missing_tools = sorted(
            set(workflow.required_tools)
            - self._create_tools().names()
        )
        if missing_tools:
            missing = ", ".join(missing_tools)
            raise ValueError(
                f"Workflow {workflow.command} requires unavailable tool(s): {missing}. "
                "Start the server with network tools enabled."
            )
        if session_id is None:
            session_id = self.create_session()
        else:
            self.get_session(session_id)
        self.session_workflows[session_id] = workflow.key
        return {
            "session_id": session_id,
            "workflow": workflow.to_dict(),
            "active": True,
        }

    def voice_config(self) -> dict[str, Any]:
        live_requested = self.voice_provider in {"auto", "gemini-live"}
        live_available = live_requested and self.voice_token_client.available()
        if self.voice_provider == "browser":
            unavailable_reason = "Server started with --voice-provider browser."
        else:
            unavailable_reason = self.voice_token_client.unavailable_reason()
        selected_provider = "gemini-live" if live_available else "browser-web-speech"
        return {
            "voice_provider": self.voice_provider,
            "selected_provider": selected_provider,
            "live_available": live_available,
            "fallback_available": True,
            "gemini_live_model": self.voice_model,
            "unavailable_reason": None if live_available else unavailable_reason,
        }

    def create_voice_token(
        self,
        purpose: str,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        if self.voice_provider == "browser":
            raise GeminiLiveTokenError(
                "Gemini Live voice is disabled by --voice-provider browser."
            )
        session_id, _session = self.get_session(session_id)
        payload = self.voice_token_client.create_token(purpose, session_id=session_id)
        payload["session_id"] = session_id
        return payload


def serialize_result(result, model_selection: ModelSelection | None = None) -> dict[str, Any]:
    payload = {
        "final_answer": result.final_answer,
        "evaluation": result.evaluation,
        "run_id": result.run_id,
        "steps": [step.__dict__ for step in result.state.steps],
    }
    if model_selection is not None:
        payload["model"] = model_selection.to_dict()
    return payload


def make_handler(app: AgentServerApp):
    class AgentRequestHandler(BaseHTTPRequestHandler):
        server_version = f"agentic-loop/{__version__}"

        def log_message(self, format, *args):
            return

        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path in {"/", "/voice"}:
                self._send_html(voice_page_html(__version__))
                return
            if parsed.path == "/voice/config":
                self._send_json(app.voice_config())
                return
            if parsed.path == "/health":
                self._send_json({"ok": True, "version": __version__})
                return
            if parsed.path == "/tools":
                self._send_json(
                    {
                        "tools": create_default_tools(
                            enable_network=app.enable_network_tools
                        ).schemas(),
                        "network_tools_enabled": app.enable_network_tools,
                        "registry": app.tool_registry(),
                    }
                )
                return
            if parsed.path == "/events":
                query = parse_qs(parsed.query)
                session_id = self._first(query, "session_id")
                after = int(self._first(query, "after") or "0")
                follow = (self._first(query, "follow") or "").lower() in {"1", "true", "yes"}
                timeout_s = float(self._first(query, "timeout") or "30")
                if follow:
                    self._send_sse_follow(app, session_id, after, timeout_s)
                else:
                    self._send_sse(app.events(session_id=session_id, after_id=after))
                return
            if parsed.path == "/sessions":
                self._send_json({"sessions": app.list_sessions()})
                return
            if parsed.path == "/memory":
                self._send_json({"records": app.memory_records()})
                return
            if parsed.path == "/learning/drafts":
                query = parse_qs(parsed.query)
                status = self._first(query, "status")
                self._send_json({"drafts": app.learning_drafts(status=status or "draft")})
                return
            if parsed.path == "/skills":
                query = parse_qs(parsed.query)
                status = self._first(query, "status")
                self._send_json({"skills": app.skills(status=status or "active")})
                return
            if parsed.path.startswith("/skills/"):
                key = parsed.path[len("/skills/"):].strip("/")
                if not key:
                    self._send_json({"error": "not found"}, status=404)
                    return
                try:
                    self._send_json({"skill": app.skill(key)})
                except KeyError as exc:
                    self._send_json({"error": "KeyError", "message": str(exc)}, status=404)
                return
            if parsed.path == "/registry/tools":
                self._send_json({"tools": app.tool_registry()})
                return
            if parsed.path == "/registry/ui":
                self._send_json({"components": app.ui_registry()})
                return
            if parsed.path == "/registry/rules":
                query = parse_qs(parsed.query)
                session_id = self._first(query, "session_id")
                self._send_json({"rules": app.rule_registry(session_id=session_id)})
                return
            if parsed.path == "/registry/workflows":
                self._send_json({"workflows": app.workflow_registry()})
                return
            if parsed.path == "/registry/models":
                query = parse_qs(parsed.query)
                session_id = self._first(query, "session_id")
                self._send_json(app.model_registry(session_id=session_id))
                return
            self._send_json({"error": "not found"}, status=404)

        def do_POST(self):
            try:
                body = self._read_json()
                if self.path == "/sessions":
                    model_selection = app.model_selection_from_payload(body)
                    session_id = app.create_session(model_selection)
                    self._send_json(
                        {
                            "session_id": session_id,
                            "model": model_selection.to_dict(),
                        }
                    )
                    return
                if self.path == "/voice/gemini/token":
                    purpose = body.get("purpose")
                    if not isinstance(purpose, str) or not purpose.strip():
                        raise ValueError("request requires purpose")
                    self._send_json(
                        app.create_voice_token(
                            purpose.strip(),
                            session_id=body.get("session_id"),
                        )
                    )
                    return
                if self.path == "/learning/drafts/approve":
                    draft_id = self._require_int(body, "id", "draft_id")
                    self._send_json(app.approve_learning_draft(draft_id))
                    return
                if self.path == "/learning/drafts/reject":
                    draft_id = self._require_int(body, "id", "draft_id")
                    self._send_json(app.reject_learning_draft(draft_id))
                    return
                if self.path == "/skills/archive":
                    key = body.get("key") or body.get("skill")
                    if not isinstance(key, str) or not key.strip():
                        raise ValueError("request requires key or skill")
                    self._send_json({"skill": app.archive_skill(key.strip())})
                    return
                if self.path == "/chat":
                    message = self._require_message(body)
                    enabled_rules, disabled_rules = self._rule_overrides(body)
                    model_selection = app.model_selection_from_payload(body, body.get("session_id"))
                    self._send_json(
                        app.chat(
                            message,
                            body.get("session_id"),
                            enabled_rule_keys=enabled_rules,
                            disabled_rule_keys=disabled_rules,
                            workflow_key=body.get("workflow"),
                            model_selection=model_selection,
                        )
                    )
                    return
                if self.path == "/run":
                    message = self._require_message(body)
                    enabled_rules, disabled_rules = self._rule_overrides(body)
                    model_selection = app.model_selection_from_payload(body)
                    self._send_json(
                        app.run_once(
                            message,
                            enabled_rule_keys=enabled_rules,
                            disabled_rule_keys=disabled_rules,
                            workflow_key=body.get("workflow"),
                            model_selection=model_selection,
                        )
                    )
                    return
                if self.path == "/models/select":
                    model_selection = app.model_selection_from_payload(body, body.get("session_id"))
                    self._send_json(
                        app.select_model(
                            model_selection,
                            session_id=body.get("session_id"),
                        )
                    )
                    return
                if self.path == "/rules/toggle":
                    rule_key = body.get("rule") or body.get("key")
                    if not isinstance(rule_key, str) or not rule_key.strip():
                        raise ValueError("request requires rule or key")
                    enabled = self._as_bool(body.get("enabled"))
                    scope_type = body.get("scope_type") or body.get("scope") or "global"
                    self._send_json(
                        app.toggle_rule(
                            rule_key.strip(),
                            enabled,
                            scope_type=scope_type,
                            session_id=body.get("session_id"),
                        )
                    )
                    return
                if self.path == "/workflows/start":
                    workflow_key = body.get("workflow") or body.get("key")
                    if not isinstance(workflow_key, str) or not workflow_key.strip():
                        raise ValueError("request requires workflow or key")
                    message = body.get("message") or body.get("goal")
                    self._send_json(
                        app.start_workflow(
                            workflow_key.strip(),
                            session_id=body.get("session_id"),
                            message=message.strip() if isinstance(message, str) and message.strip() else None,
                        )
                    )
                    return
                self._send_json({"error": "not found"}, status=404)
            except Exception as exc:
                self._send_json(
                    {"error": type(exc).__name__, "message": str(exc)},
                    status=400,
                )

        def _read_json(self):
            length = int(self.headers.get("Content-Length", "0"))
            if length == 0:
                return {}
            raw = self.rfile.read(length).decode("utf-8")
            return json.loads(raw)

        def _require_message(self, body):
            message = body.get("message") or body.get("goal")
            if not isinstance(message, str) or not message.strip():
                raise ValueError("request requires non-empty message or goal")
            return message.strip()

        def _require_int(self, body, *keys):
            for key in keys:
                value = body.get(key)
                if value is None:
                    continue
                try:
                    return int(value)
                except (TypeError, ValueError):
                    break
            joined = " or ".join(keys)
            raise ValueError(f"request requires integer {joined}")

        def _rule_overrides(self, body):
            enabled = []
            disabled = []
            rules = body.get("rules")
            if isinstance(rules, list):
                enabled.extend(item for item in rules if isinstance(item, str))
            elif isinstance(rules, dict):
                enabled.extend(item for item in rules.get("enable", []) if isinstance(item, str))
                disabled.extend(item for item in rules.get("disable", []) if isinstance(item, str))
            enabled.extend(item for item in (body.get("enabled_rules") or []) if isinstance(item, str))
            disabled.extend(item for item in (body.get("disabled_rules") or []) if isinstance(item, str))
            return enabled, disabled

        def _as_bool(self, value):
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                return value.lower() in {"1", "true", "yes", "on"}
            return bool(value)

        def _first(self, query, key):
            values = query.get(key)
            if not values:
                return None
            return values[0]

        def _send_json(self, payload, status=200):
            raw = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _send_sse(self, events, status=200):
            raw = format_sse_events(events).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _send_sse_follow(self, app, session_id, after, timeout_s, status=200):
            self.send_response(status)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            deadline = time.monotonic() + max(0.0, timeout_s)
            last_id = after
            while time.monotonic() <= deadline:
                events = app.events(session_id=session_id, after_id=last_id)
                if events:
                    raw = format_sse_events(events).encode("utf-8")
                    self.wfile.write(raw)
                    self.wfile.flush()
                    last_id = int(events[-1]["id"])
                else:
                    self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
                time.sleep(0.25)

        def _send_html(self, html, status=200):
            raw = html.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    return AgentRequestHandler


def serve(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="agentic-loop serve")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--workspace", default="sample_workspace")
    parser.add_argument("--db", default=".agentic/agentic.db")
    parser.add_argument("--memory", default=None, help="Use legacy JSONL memory at this path.")
    parser.add_argument("--trace", default=None, help="Optional JSONL trace export path.")
    parser.add_argument("--max-steps", type=int, default=8)
    parser.add_argument(
        "--provider",
        choices=["rule", "ollama", "openai", "openai-compatible", "gemini", "localai"],
        default=DEFAULT_INTERACTIVE_PROVIDER,
        help="Default provider for requests that do not choose one.",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Default model for requests that do not choose one.",
    )
    parser.add_argument("--ollama-host", default=DEFAULT_OLLAMA_HOST)
    parser.add_argument("--api-base", default=None)
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--write-root", action="append", default=[])
    parser.add_argument("--approval-root", action="append", default=[])
    parser.add_argument(
        "--enable-network-tools",
        action="store_true",
        dest="enable_network_tools",
        default=True,
        help="Expose search_web, search_news, and fetch_url tools. Enabled by default for serve.",
    )
    parser.add_argument(
        "--disable-network-tools",
        action="store_false",
        dest="enable_network_tools",
        help="Disable search_web, search_news, and fetch_url tools for the served API.",
    )
    parser.add_argument(
        "--voice-provider",
        choices=sorted(VOICE_PROVIDERS),
        default="auto",
        help="Voice mode backend: auto uses Gemini Live when configured, else browser fallback.",
    )
    parser.add_argument(
        "--voice-model",
        default=os.environ.get("AGENTIC_LOOP_GEMINI_LIVE_MODEL") or DEFAULT_GEMINI_LIVE_MODEL,
        help="Gemini Live model used for realtime browser voice.",
    )
    parser.add_argument(
        "--learning",
        choices=sorted(LEARNING_MODES),
        default="draft",
        help="Learning loop mode. Draft records suggestions without auto-activating skills.",
    )
    parser.add_argument(
        "--learning-threshold",
        type=int,
        default=2,
        help="Times a pattern must recur before a procedural skill draft is proposed.",
    )
    args = parser.parse_args(argv)

    write_roots = ["outputs", *args.write_root]
    model_name = args.model
    if args.provider == DEFAULT_INTERACTIVE_PROVIDER and model_name is None:
        model_name = DEFAULT_INTERACTIVE_MODEL
    default_model_selection = ModelSelection.from_values(
        provider=args.provider,
        model_name=model_name,
        ollama_host=args.ollama_host,
        api_base=args.api_base,
        api_key=args.api_key,
    )
    if not ensure_ollama_model_available(default_model_selection):
        return 1

    app = AgentServerApp(
        workspace=args.workspace,
        memory_path=args.memory,
        trace_path=args.trace,
        db_path=args.db,
        max_steps=args.max_steps,
        provider=default_model_selection.provider,
        model_name=default_model_selection.model_name,
        ollama_host=default_model_selection.ollama_host or args.ollama_host,
        api_base=default_model_selection.api_base,
        api_key=default_model_selection.api_key,
        write_roots=write_roots,
        approval_required_roots=args.approval_root,
        enable_network_tools=args.enable_network_tools,
        voice_provider=args.voice_provider,
        voice_model=args.voice_model,
        learning_mode=args.learning,
        learning_threshold=args.learning_threshold,
    )
    server = ThreadingHTTPServer((args.host, args.port), make_handler(app))
    print(f"agentic-loop serving on http://{args.host}:{args.port}")
    print(f"voice mode available at http://{args.host}:{args.port}/voice")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()
        return 0
    return 0
