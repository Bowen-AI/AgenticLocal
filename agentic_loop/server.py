import argparse
import json
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from .factory import create_controller
from .session import AgentSession
from .storage import SQLiteStore
from .tools import create_default_tools
from .types import Message
from .version import __version__
from .voice import voice_page_html


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
        model_name: str = "gemma3:270m",
        ollama_host: str = "http://127.0.0.1:11434",
        api_base: str | None = None,
        api_key: str | None = None,
        read_roots: list[str] | None = None,
        write_roots: list[str] | None = None,
        approval_required_roots: list[str] | None = None,
        storage: SQLiteStore | None = None,
        enable_network_tools: bool = False,
    ):
        self.workspace = workspace
        self.memory_path = memory_path
        self.trace_path = trace_path
        self.db_path = db_path
        self.max_steps = max_steps
        self.provider = provider
        self.model_name = model_name
        self.ollama_host = ollama_host
        self.api_base = api_base
        self.api_key = api_key
        self.read_roots = read_roots
        self.write_roots = write_roots
        self.approval_required_roots = approval_required_roots
        self.enable_network_tools = enable_network_tools
        self.storage = storage or SQLiteStore(db_path or ".agentic/agentic.db")
        self.sessions: dict[str, AgentSession] = {}
        self.storage.seed_tool_registry(
            create_default_tools(enable_network=enable_network_tools).metadata()
        )
        self.storage.seed_default_ui_registry()

    def create_session(self) -> str:
        session_id = uuid.uuid4().hex
        self.storage.ensure_session(session_id)
        self.sessions[session_id] = self._make_session(session_id, [])
        return session_id

    def get_session(self, session_id: str | None) -> tuple[str, AgentSession]:
        if not session_id:
            session_id = self.create_session()
        if session_id not in self.sessions:
            if not self.storage.session_exists(session_id):
                raise KeyError(f"unknown session_id: {session_id}")
            self.sessions[session_id] = self._make_session(
                session_id,
                self.storage.load_messages(session_id),
            )
        return session_id, self.sessions[session_id]

    def _make_controller(self):
        return create_controller(
            workspace=self.workspace,
            memory_path=self.memory_path,
            trace_path=self.trace_path,
            db_path=self.db_path,
            max_steps=self.max_steps,
            provider=self.provider,
            model_name=self.model_name,
            ollama_host=self.ollama_host,
            api_base=self.api_base,
            api_key=self.api_key,
            read_roots=self.read_roots,
            write_roots=self.write_roots,
            approval_required_roots=self.approval_required_roots,
            storage=self.storage,
            enable_network_tools=self.enable_network_tools,
        )

    def _make_session(self, session_id: str, history: list[Message]) -> AgentSession:
        return AgentSession(
            self._make_controller(),
            history=history,
            session_id=session_id,
            storage=self.storage,
        )

    def run_once(self, message: str) -> dict[str, Any]:
        controller = self._make_controller()
        result = controller.run(message)
        return serialize_result(result)

    def chat(self, message: str, session_id: str | None = None) -> dict[str, Any]:
        session_id, session = self.get_session(session_id)
        result = session.ask(message)
        payload = serialize_result(result)
        payload["session_id"] = session_id
        payload["transcript"] = session.transcript()
        return payload

    def events(self, session_id: str | None = None, after_id: int = 0) -> list[dict[str, Any]]:
        return self.storage.events_after(session_id=session_id, after_id=after_id)

    def list_sessions(self) -> list[dict[str, Any]]:
        return self.storage.list_sessions()

    def memory_records(self) -> list[dict[str, Any]]:
        return [record.__dict__ for record in self.storage.all()]

    def tool_registry(self) -> list[dict[str, Any]]:
        return self.storage.list_tool_registry()

    def ui_registry(self) -> list[dict[str, Any]]:
        return self.storage.list_ui_registry()


def serialize_result(result) -> dict[str, Any]:
    return {
        "final_answer": result.final_answer,
        "evaluation": result.evaluation,
        "run_id": result.run_id,
        "steps": [step.__dict__ for step in result.state.steps],
    }


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
            if parsed.path == "/registry/tools":
                self._send_json({"tools": app.tool_registry()})
                return
            if parsed.path == "/registry/ui":
                self._send_json({"components": app.ui_registry()})
                return
            self._send_json({"error": "not found"}, status=404)

        def do_POST(self):
            try:
                body = self._read_json()
                if self.path == "/sessions":
                    session_id = app.create_session()
                    self._send_json({"session_id": session_id})
                    return
                if self.path == "/chat":
                    message = self._require_message(body)
                    self._send_json(app.chat(message, body.get("session_id")))
                    return
                if self.path == "/run":
                    message = self._require_message(body)
                    self._send_json(app.run_once(message))
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
        choices=["rule", "ollama", "openai", "openai-compatible", "localai"],
        default="rule",
    )
    parser.add_argument("--model", default="gemma3:270m")
    parser.add_argument("--ollama-host", default="http://127.0.0.1:11434")
    parser.add_argument("--api-base", default=None)
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--write-root", action="append", default=[])
    parser.add_argument("--approval-root", action="append", default=[])
    parser.add_argument(
        "--enable-network-tools",
        action="store_true",
        help="Expose search_web, search_news, and fetch_url tools.",
    )
    args = parser.parse_args(argv)

    write_roots = ["outputs", *args.write_root]

    app = AgentServerApp(
        workspace=args.workspace,
        memory_path=args.memory,
        trace_path=args.trace,
        db_path=args.db,
        max_steps=args.max_steps,
        provider=args.provider,
        model_name=args.model,
        ollama_host=args.ollama_host,
        api_base=args.api_base,
        api_key=args.api_key,
        write_roots=write_roots,
        approval_required_roots=args.approval_root,
        enable_network_tools=args.enable_network_tools,
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
