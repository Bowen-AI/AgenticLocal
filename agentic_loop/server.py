import argparse
import json
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .factory import create_controller
from .session import AgentSession
from .tools import create_default_tools
from .version import __version__
from .voice import voice_page_html


class AgentServerApp:
    def __init__(
        self,
        workspace: str = "sample_workspace",
        memory_path: str = ".agentic-memory.jsonl",
        trace_path: str = ".agentic-trace.jsonl",
        max_steps: int = 8,
        provider: str = "rule",
        model_name: str = "gemma3:270m",
        ollama_host: str = "http://127.0.0.1:11434",
    ):
        self.workspace = workspace
        self.memory_path = memory_path
        self.trace_path = trace_path
        self.max_steps = max_steps
        self.provider = provider
        self.model_name = model_name
        self.ollama_host = ollama_host
        self.sessions: dict[str, AgentSession] = {}

    def create_session(self) -> str:
        session_id = uuid.uuid4().hex
        self.sessions[session_id] = AgentSession(
            create_controller(
                workspace=self.workspace,
                memory_path=self.memory_path,
                trace_path=self.trace_path,
                max_steps=self.max_steps,
                provider=self.provider,
                model_name=self.model_name,
                ollama_host=self.ollama_host,
            )
        )
        return session_id

    def get_session(self, session_id: str | None) -> tuple[str, AgentSession]:
        if not session_id:
            session_id = self.create_session()
        if session_id not in self.sessions:
            raise KeyError(f"unknown session_id: {session_id}")
        return session_id, self.sessions[session_id]

    def run_once(self, message: str) -> dict[str, Any]:
        controller = create_controller(
            workspace=self.workspace,
            memory_path=self.memory_path,
            trace_path=self.trace_path,
            max_steps=self.max_steps,
            provider=self.provider,
            model_name=self.model_name,
            ollama_host=self.ollama_host,
        )
        result = controller.run(message)
        return serialize_result(result)

    def chat(self, message: str, session_id: str | None = None) -> dict[str, Any]:
        session_id, session = self.get_session(session_id)
        result = session.ask(message)
        payload = serialize_result(result)
        payload["session_id"] = session_id
        payload["transcript"] = session.transcript()
        return payload


def serialize_result(result) -> dict[str, Any]:
    return {
        "final_answer": result.final_answer,
        "evaluation": result.evaluation,
        "steps": [step.__dict__ for step in result.state.steps],
    }


def make_handler(app: AgentServerApp):
    class AgentRequestHandler(BaseHTTPRequestHandler):
        server_version = f"agentic-loop/{__version__}"

        def log_message(self, format, *args):
            return

        def do_GET(self):
            if self.path in {"/", "/voice"}:
                self._send_html(voice_page_html(__version__))
                return
            if self.path == "/health":
                self._send_json({"ok": True, "version": __version__})
                return
            if self.path == "/tools":
                self._send_json({"tools": create_default_tools().schemas()})
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

        def _send_json(self, payload, status=200):
            raw = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

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
    parser.add_argument("--memory", default=".agentic-memory.jsonl")
    parser.add_argument("--trace", default=".agentic-trace.jsonl")
    parser.add_argument("--max-steps", type=int, default=8)
    parser.add_argument("--provider", choices=["rule", "ollama"], default="rule")
    parser.add_argument("--model", default="gemma3:270m")
    parser.add_argument("--ollama-host", default="http://127.0.0.1:11434")
    args = parser.parse_args(argv)

    app = AgentServerApp(
        workspace=args.workspace,
        memory_path=args.memory,
        trace_path=args.trace,
        max_steps=args.max_steps,
        provider=args.provider,
        model_name=args.model,
        ollama_host=args.ollama_host,
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
