import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from agentic_loop import (
    AgentController,
    AgentSession,
    BrowserSpeechVoiceAdapter,
    GeminiLiveTokenClient,
    GeminiLiveTokenError,
    GeminiLiveVoiceAdapter,
    JsonlMemory,
    ModelSelection,
    ModelResponse,
    RealtimeVoiceAdapterSpec,
    RuleBasedModel,
    ScriptedModel,
    SQLiteStore,
    VoiceAdapter,
    WorkspaceAccessConfig,
    WorkspacePolicy,
    create_default_tools,
)
from agentic_loop.cli import main as cli_main
from agentic_loop.chat import run_chat
from agentic_loop.ollama_model import OllamaChatModel
from agentic_loop.ollama_runtime import ensure_ollama_model_available, ollama_model_installed
from agentic_loop.factory import create_controller
from agentic_loop.model_selection import DEFAULT_INTERACTIVE_MODEL, parse_model_command
from agentic_loop.server import AgentServerApp, format_sse_events, make_handler, serve as serve_command
from agentic_loop.skills import render_skill_markdown
from agentic_loop.tools import ToolContext
from agentic_loop.voice import voice_page_html


REPO_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_WORKSPACE = REPO_ROOT / "sample_workspace"


class FakeWebClient:
    def get_json(self, url, timeout_s=10.0):
        return {
            "Heading": "Agentic AI",
            "AbstractText": "Agentic AI systems can use tools to complete tasks.",
            "AbstractURL": "https://example.test/agentic-ai",
            "RelatedTopics": [
                {
                    "Text": "Tool use - Models can request runtime tools.",
                    "FirstURL": "https://example.test/tool-use",
                }
            ],
        }

    def get_text(self, url, timeout_s=10.0):
        if "news.google.com" in url:
            return """<?xml version="1.0" encoding="UTF-8"?>
            <rss><channel>
              <item>
                <title>Agentic AI project launches local runtime</title>
                <link>https://news.example.test/local-runtime</link>
                <pubDate>Thu, 21 May 2026 10:00:00 GMT</pubDate>
                <source>Example News</source>
              </item>
            </channel></rss>"""
        return "<html><head><title>Example Page</title></head><body>Hello from a fetched page.</body></html>"


class FakeGeminiTokenClient:
    def __init__(self, available=True):
        self.available_value = available
        self.calls = []

    def available(self):
        return self.available_value

    def unavailable_reason(self):
        if self.available_value:
            return None
        return "fake token client unavailable"

    def create_token(self, purpose, session_id=None):
        self.calls.append((purpose, session_id))
        return {
            "token": f"auth_tokens/{purpose}",
            "websocket_url": "wss://gemini.example.test/live",
            "model": "test-live-model",
            "purpose": purpose,
            "session_id": session_id,
            "expire_time": "2026-05-23T12:30:00Z",
            "new_session_expire_time": "2026-05-23T12:01:00Z",
            "setup": {
                "model": "models/test-live-model",
                "generationConfig": {"responseModalities": ["TEXT"]},
            },
        }


class AgenticLoopTest(unittest.TestCase):
    def make_controller(self, model=None, workspace=None, memory=None, max_steps=8):
        workspace = Path(workspace or SAMPLE_WORKSPACE)
        return AgentController(
            model=model or RuleBasedModel(),
            tools=create_default_tools(),
            policy=WorkspacePolicy(workspace),
            workspace_root=workspace,
            memory=memory,
            max_steps=max_steps,
        )

    def make_network_controller(self, model=None, workspace=None, max_steps=8):
        workspace = Path(workspace or SAMPLE_WORKSPACE)
        return AgentController(
            model=model or RuleBasedModel(),
            tools=create_default_tools(enable_network=True),
            policy=WorkspacePolicy(workspace),
            workspace_root=workspace,
            max_steps=max_steps,
            web_client=FakeWebClient(),
        )

    def make_controller_with_policy(
        self,
        model=None,
        workspace=None,
        write_roots=None,
        approval_required_roots=None,
    ):
        workspace = Path(workspace or SAMPLE_WORKSPACE)
        access = WorkspaceAccessConfig(
            workspace,
            write_roots=write_roots,
            approval_required_roots=approval_required_roots,
        )
        return AgentController(
            model=model or RuleBasedModel(),
            tools=create_default_tools(),
            policy=WorkspacePolicy(workspace, access=access),
            workspace_root=workspace,
            max_steps=8,
        )

    def _call_handler_get(self, handler_cls, path):
        captured = {}
        handler = object.__new__(handler_cls)
        handler.path = path
        handler._send_json = lambda payload, status=200: captured.update(
            {"payload": payload, "status": status}
        )
        handler._send_html = lambda html, status=200: captured.update(
            {"html": html, "status": status}
        )
        handler._send_sse = lambda events, status=200: captured.update(
            {"events": events, "status": status}
        )
        handler.do_GET()
        return captured

    def _call_handler_post(self, handler_cls, path, body):
        captured = {}
        handler = object.__new__(handler_cls)
        handler.path = path
        handler._read_json = lambda: body
        handler._send_json = lambda payload, status=200: captured.update(
            {"payload": payload, "status": status}
        )
        handler.do_POST()
        return captured

    def test_agent_lists_files_through_tool_loop(self):
        result = self.make_controller().run("List files in the workspace.")

        self.assertIn("sample_workspace", str(SAMPLE_WORKSPACE))
        self.assertIn("I found", result.final_answer)
        self.assertIn("data/sample.csv", result.final_answer)
        self.assertEqual(result.state.steps[0].tool_name, "list_files")
        self.assertTrue(result.evaluation["has_final_answer"])

    def test_agent_reads_file_through_tool_loop(self):
        result = self.make_controller().run("Read notes/example.txt and summarize it.")

        self.assertIn("I read notes/example.txt", result.final_answer)
        self.assertEqual(result.state.steps[0].tool_name, "read_file")

    def test_agent_inspects_csv(self):
        result = self.make_controller().run("Inspect data/sample.csv as a dataset.")

        self.assertIn("4 row(s)", result.final_answer)
        self.assertIn("knee_moment", result.final_answer)
        observation = result.state.steps[0].observation
        self.assertEqual(observation["missing_values"]["acc_y"], 1)

    def test_agent_writes_only_to_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            (workspace / "outputs").mkdir()
            result = self.make_controller(workspace=workspace).run(
                "Write a note saying hello from the agent."
            )
            output = workspace / "outputs" / "agent_note.txt"
            self.assertTrue(output.exists())
            self.assertEqual(output.read_text(encoding="utf-8"), "hello from the agent.")
            self.assertIn("I wrote outputs/agent_note.txt", result.final_answer)

    def test_configured_write_root_allows_drafts(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            model = ScriptedModel(
                [
                    ModelResponse.call(
                        "write_file",
                        {"path": "drafts/note.txt", "content": "hello drafts"},
                        "call_drafts",
                    ),
                    ModelResponse.final("draft saved"),
                ]
            )
            result = self.make_controller_with_policy(
                model=model,
                workspace=workspace,
                write_roots=("outputs", "drafts"),
            ).run("Write a draft note")

            output = workspace / "drafts" / "note.txt"
            self.assertTrue(output.exists())
            self.assertEqual(output.read_text(encoding="utf-8"), "hello drafts")
            self.assertTrue(result.state.steps[0].allowed)

    def test_policy_denies_outside_read(self):
        model = ScriptedModel(
            [
                ModelResponse.call("read_file", {"path": "../secret.txt"}, "call_bad"),
                ModelResponse.final("stopped after denial"),
            ]
        )
        result = self.make_controller(model=model).run("Read ../secret.txt")

        self.assertFalse(result.state.steps[0].allowed)
        self.assertIn("path escapes workspace", result.state.steps[0].observation)
        self.assertEqual(result.evaluation["denied_steps"], 1)

    def test_policy_denies_write_outside_outputs(self):
        model = ScriptedModel(
            [
                ModelResponse.call(
                    "write_file",
                    {"path": "raw.txt", "content": "bad"},
                    "call_bad_write",
                ),
                ModelResponse.final("stopped after denial"),
            ]
        )
        result = self.make_controller(model=model).run("Write raw.txt")

        self.assertFalse(result.state.steps[0].allowed)
        self.assertIn("configured write roots (outputs)", result.state.steps[0].observation)

    def test_policy_marks_approval_required_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            model = ScriptedModel(
                [
                    ModelResponse.call(
                        "write_file",
                        {"path": "reviewed/note.txt", "content": "needs approval"},
                        "call_reviewed",
                    ),
                    ModelResponse.final("stopped after approval request"),
                ]
            )
            result = self.make_controller_with_policy(
                model=model,
                workspace=workspace,
                write_roots=("outputs", "reviewed"),
                approval_required_roots=("reviewed",),
            ).run("Write reviewed/note.txt")

            self.assertEqual(result.state.steps[0].action, "approval_required")
            self.assertFalse((workspace / "reviewed" / "note.txt").exists())

    def test_policy_denies_symlink_escape(self):
        if not hasattr(os, "symlink"):
            self.skipTest("symlink not supported")

        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            workspace.mkdir()
            (workspace / "outputs").mkdir()
            outside = Path(tmp) / "outside.txt"
            outside.write_text("secret", encoding="utf-8")
            (workspace / "outside_link.txt").symlink_to(outside)

            model = ScriptedModel(
                [
                    ModelResponse.call(
                        "read_file",
                        {"path": "outside_link.txt"},
                        "call_symlink",
                    ),
                    ModelResponse.final("stopped after denial"),
                ]
            )
            result = self.make_controller(model=model, workspace=workspace).run(
                "Read outside_link.txt"
            )

            self.assertFalse(result.state.steps[0].allowed)
            self.assertIn("path escapes workspace", result.state.steps[0].observation)

    def test_memory_remember_and_recall(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory = JsonlMemory(Path(tmp) / "memory.jsonl")
            remember_result = self.make_controller(memory=memory).run(
                "Remember project language is python."
            )
            recall_result = self.make_controller(memory=memory).run(
                "What is the project language?"
            )

            self.assertIn("I remembered project_language", remember_result.final_answer)
            self.assertIn("project_language=python", recall_result.final_answer)

    def test_sqlite_memory_remember_and_recall(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory = SQLiteStore(Path(tmp) / "agentic.db")
            remember_result = self.make_controller(memory=memory).run(
                "Remember project language is python."
            )
            recall_result = self.make_controller(memory=memory).run(
                "What is the project language?"
            )

            self.assertIn("I remembered project_language", remember_result.final_answer)
            self.assertIn("project_language=python", recall_result.final_answer)
            self.assertEqual(memory.latest("project_language").value, "python")

    def test_interactive_session_keeps_transcript_and_memory(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory = JsonlMemory(Path(tmp) / "memory.jsonl")
            session = AgentSession(self.make_controller(memory=memory))

            first = session.ask("Remember project language is python.")
            second = session.ask("What is the project language?")
            third = session.ask("Inspect data/sample.csv as a dataset.")

            self.assertIn("I remembered project_language", first.final_answer)
            self.assertIn("project_language=python", second.final_answer)
            self.assertIn("4 row(s)", third.final_answer)
            self.assertEqual(len(session.transcript()), 6)
            self.assertEqual(session.transcript()[0]["role"], "user")

    def test_direct_chat_is_more_helpful(self):
        hello = self.make_controller().run("hello")
        vague = self.make_controller().run("??")

        self.assertIn("deterministic rule provider", hello.final_answer)
        self.assertIn("Available tools", vague.final_answer)

    def test_agent_answers_current_date_through_tool(self):
        result = self.make_controller().run("what is today's date")

        self.assertEqual(result.state.steps[0].tool_name, "current_datetime")
        self.assertIn("Today is", result.final_answer)
        self.assertIn("date", result.state.steps[0].observation)

    def test_max_step_stop_condition(self):
        model = ScriptedModel(
            [
                ModelResponse.call("list_files", {"path": "."}, "call_1"),
                ModelResponse.call("list_files", {"path": "."}, "call_2"),
            ]
        )
        result = self.make_controller(model=model, max_steps=1).run("Loop forever")

        self.assertEqual(result.final_answer, "Agent stopped because the step limit was reached.")
        self.assertEqual(result.evaluation["steps"], 1)

    def test_trace_json_output_shape_from_state(self):
        result = self.make_controller().run("Inspect data/sample.csv")
        payload = {
            "final_answer": result.final_answer,
            "steps": [step.__dict__ for step in result.state.steps],
        }
        encoded = json.dumps(payload)
        self.assertIn("inspect_csv", encoded)

    def test_ollama_model_parses_tool_call(self):
        class FakeOllama(OllamaChatModel):
            payload = None

            def _post(self, path, payload):
                self.__class__.payload = payload
                return {
                    "message": {
                        "role": "assistant",
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "function": {
                                    "name": "inspect_csv",
                                    "arguments": {"path": "data/sample.csv"},
                                },
                            }
                        ],
                    }
                }

        response = FakeOllama(model="test-model").respond([], create_default_tools().schemas(), "")
        self.assertEqual(response.tool_call.name, "inspect_csv")
        self.assertEqual(response.tool_call.arguments["path"], "data/sample.csv")
        self.assertIs(FakeOllama.payload["think"], False)

    def test_ollama_model_can_enable_thinking(self):
        class FakeOllama(OllamaChatModel):
            payload = None

            def _post(self, path, payload):
                self.__class__.payload = payload
                return {"message": {"role": "assistant", "content": "OK"}}

        response = FakeOllama(model="test-model", think="low").respond([], [], "")

        self.assertEqual(response.final_answer, "OK")
        self.assertEqual(FakeOllama.payload["think"], "low")

    def test_ollama_model_falls_back_when_tools_not_supported(self):
        class FakeOllama(OllamaChatModel):
            def _post(self, path, payload):
                if payload.get("tools"):
                    data = {"message": {"role": "assistant", "content": "OK"}}
                    data["_retried_without_tools"] = True
                    return data
                return {"message": {"role": "assistant", "content": "OK"}}

        response = FakeOllama(model="test-model").respond([], create_default_tools().schemas(), "")
        self.assertIn("OK", response.final_answer)
        self.assertIn("does not support native tool calling", response.final_answer)

    def test_server_app_chat_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = AgentServerApp(
                workspace=str(SAMPLE_WORKSPACE),
                db_path=str(Path(tmp) / "agentic.db"),
            )
            first = app.chat("Remember project language is python.")
            second = app.chat("What is the project language?", first["session_id"])
            one_shot = app.run_once("Inspect data/sample.csv as a dataset.")

            self.assertEqual(first["session_id"], second["session_id"])
            self.assertIn("I remembered project_language", first["final_answer"])
            self.assertIn("project_language=python", second["final_answer"])
            self.assertEqual(len(second["transcript"]), 4)
            self.assertIn("4 row(s)", one_shot["final_answer"])

    def test_server_session_persists_across_app_recreation(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "agentic.db")
            first_app = AgentServerApp(workspace=str(SAMPLE_WORKSPACE), db_path=db_path)
            first = first_app.chat("Remember project language is python.")

            second_app = AgentServerApp(workspace=str(SAMPLE_WORKSPACE), db_path=db_path)
            second = second_app.chat("What is the project language?", first["session_id"])

            self.assertEqual(first["session_id"], second["session_id"])
            self.assertIn("project_language=python", second["final_answer"])
            self.assertEqual(len(second["transcript"]), 4)

    def test_sqlite_events_and_registries_are_persisted(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = AgentServerApp(
                workspace=str(SAMPLE_WORKSPACE),
                db_path=str(Path(tmp) / "agentic.db"),
            )
            result = app.run_once("Inspect data/sample.csv as a dataset.")
            events = app.events()
            event_types = [event["event_type"] for event in events]
            tool_names = {item["name"] for item in app.tool_registry()}
            ui_components = {item["component"] for item in app.ui_registry()}

            self.assertIn("run_started", event_types)
            self.assertIn("tool_requested", event_types)
            self.assertIn("tool_result", event_types)
            self.assertIn("final_answer", event_types)
            self.assertIn(result["run_id"], {event["run_id"] for event in events})
            self.assertIn("inspect_csv", tool_names)
            self.assertIn("table_preview", ui_components)

    def test_sqlite_rule_and_workflow_registries_are_persisted(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "agentic.db")
            app = AgentServerApp(workspace=str(SAMPLE_WORKSPACE), db_path=db_path)

            rules = {item["key"]: item for item in app.rule_registry()}
            workflows = {item["key"]: item for item in app.workflow_registry()}
            app.toggle_rule("max_effort", True)
            recreated = AgentServerApp(workspace=str(SAMPLE_WORKSPACE), db_path=db_path)
            recreated_rules = {item["key"]: item for item in recreated.rule_registry()}

            self.assertIn("max_effort", rules)
            self.assertIn("safe_writes", rules)
            self.assertEqual(workflows["loop"]["command"], "/loop")
            self.assertEqual(workflows["search"]["command"], "/search")
            self.assertEqual(workflows["release"]["command"], "/release")
            self.assertIn("safe_writes", workflows["release"]["rule_keys"])
            self.assertIn("read_file", workflows["release"]["required_tools"])
            self.assertTrue(recreated_rules["max_effort"]["enabled"])

    def test_active_rules_are_injected_into_model_context(self):
        class CapturingModel:
            def __init__(self):
                self.messages = []

            def respond(self, messages, tools, state_summary):
                self.messages = messages
                return ModelResponse.final("done")

        model = CapturingModel()
        result = self.make_controller(model=model).run(
            "hello",
            enabled_rule_keys={"max_effort"},
        )
        combined = "\n".join(message.content for message in model.messages)

        self.assertEqual(result.final_answer, "done")
        self.assertIn("Active rules:", combined)
        self.assertIn("max_effort", combined)

    def test_release_workflow_injects_release_prompt_and_rules(self):
        class CapturingModel:
            def __init__(self):
                self.messages = []

            def respond(self, messages, tools, state_summary):
                self.messages = messages
                return ModelResponse.final("release ready")

        model = CapturingModel()
        result = self.make_controller(model=model).run("Prepare release.", workflow_key="release")
        combined = "\n".join(message.content for message in model.messages)

        self.assertEqual(result.final_answer, "release ready")
        self.assertIn("Workflow /release is active", combined)
        self.assertIn("max_effort", combined)
        self.assertIn("safe_writes", combined)

    def test_safe_writes_rule_requires_approval_before_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            (workspace / "outputs").mkdir()
            model = ScriptedModel(
                [
                    ModelResponse.call(
                        "write_file",
                        {"path": "outputs/note.txt", "content": "needs review"},
                        "call_write",
                    ),
                    ModelResponse.final("stopped after approval"),
                ]
            )
            result = self.make_controller(model=model, workspace=workspace).run(
                "Write a note.",
                enabled_rule_keys={"safe_writes"},
            )

            self.assertEqual(result.state.steps[0].action, "approval_required")
            self.assertFalse((workspace / "outputs" / "note.txt").exists())

    def test_search_workflow_requires_network_tools(self):
        result = self.make_controller().run("Search the internet for agentic AI.", workflow_key="search")

        self.assertEqual(result.state.steps[0].action, "workflow_unavailable")
        self.assertIn("--enable-network-tools", result.final_answer)

    def test_cli_lists_rules_and_workflows(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = StringIO()
            with redirect_stdout(output):
                exit_code = cli_main(["--db", str(Path(tmp) / "agentic.db"), "--rules", "--workflows"])

            text = output.getvalue()
            self.assertEqual(exit_code, 0)
            self.assertIn("max_effort", text)
            self.assertIn("/loop", text)
            self.assertIn("/release", text)
            self.assertIn("/search", text)

    def test_sse_stream_uses_persisted_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = AgentServerApp(
                workspace=str(SAMPLE_WORKSPACE),
                db_path=str(Path(tmp) / "agentic.db"),
            )
            result = app.chat("Inspect data/sample.csv as a dataset.")
            events = app.events(session_id=result["session_id"])
            stream = format_sse_events(events)

            self.assertIn("event: run_started", stream)
            self.assertIn("event: tool_result", stream)
            self.assertIn("event: final_answer", stream)
            self.assertEqual(events, app.storage.events_after(session_id=result["session_id"]))

    def test_provider_selection_rejects_unknown_provider(self):
        with self.assertRaises(ValueError):
            create_controller(provider="unknown", db_path=None)

    def test_non_rule_provider_requires_runtime_model_selection(self):
        with self.assertRaisesRegex(ValueError, "requires a model"):
            create_controller(provider="ollama", db_path=None)

    def test_server_model_registry_and_selection_are_runtime_configurable(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = AgentServerApp(
                workspace=str(SAMPLE_WORKSPACE),
                db_path=str(Path(tmp) / "agentic.db"),
            )
            registry = app.model_registry()
            providers = {item["provider"] for item in registry["providers"]}
            selection = app.model_selection_from_payload(
                {"model": {"provider": "rule", "name": "not-used"}}
            )
            result = app.run_once("hello", model_selection=selection)
            selected = app.select_model(
                ModelSelection.from_values(provider="rule"),
                session_id=result.get("session_id"),
            )

            self.assertIn("ollama", providers)
            self.assertIn("openai", providers)
            self.assertIn("gemini", providers)
            self.assertEqual(result["model"]["provider"], "rule")
            self.assertEqual(result["model"]["model"], "not-used")
            self.assertEqual(selected["model"]["provider"], "rule")

    def test_server_rejects_incomplete_model_selection(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = AgentServerApp(
                workspace=str(SAMPLE_WORKSPACE),
                db_path=str(Path(tmp) / "agentic.db"),
            )

            with self.assertRaisesRegex(ValueError, "requires a model"):
                app.model_selection_from_payload({"provider": "ollama"})
            with self.assertRaisesRegex(ValueError, "requires api_base"):
                app.model_selection_from_payload({"provider": "gemini", "model": "gemini-model"})

    def test_serve_enables_network_tools_by_default(self):
        created_apps = []

        class FakeServer:
            def __init__(self, address, handler):
                self.address = address
                self.handler = handler

            def serve_forever(self):
                return None

        def fake_app(**kwargs):
            created_apps.append(kwargs)
            return object()

        with redirect_stdout(StringIO()), patch(
            "agentic_loop.server.AgentServerApp",
            side_effect=fake_app,
        ), patch("agentic_loop.server.ThreadingHTTPServer", FakeServer), patch(
            "agentic_loop.server.ensure_ollama_model_available",
            return_value=True,
        ):
            exit_code = serve_command(["--port", "0"])

        self.assertEqual(exit_code, 0)
        self.assertTrue(created_apps[0]["enable_network_tools"])

    def test_serve_can_disable_default_network_tools(self):
        created_apps = []

        class FakeServer:
            def __init__(self, address, handler):
                self.address = address
                self.handler = handler

            def serve_forever(self):
                return None

        def fake_app(**kwargs):
            created_apps.append(kwargs)
            return object()

        with redirect_stdout(StringIO()), patch(
            "agentic_loop.server.AgentServerApp",
            side_effect=fake_app,
        ), patch("agentic_loop.server.ThreadingHTTPServer", FakeServer), patch(
            "agentic_loop.server.ensure_ollama_model_available",
            return_value=True,
        ):
            exit_code = serve_command(["--port", "0", "--disable-network-tools"])

        self.assertEqual(exit_code, 0)
        self.assertFalse(created_apps[0]["enable_network_tools"])

    def test_serve_accepts_voice_provider_and_model(self):
        created_apps = []

        class FakeServer:
            def __init__(self, address, handler):
                self.address = address
                self.handler = handler

            def serve_forever(self):
                return None

        def fake_app(**kwargs):
            created_apps.append(kwargs)
            return object()

        with redirect_stdout(StringIO()), patch(
            "agentic_loop.server.AgentServerApp",
            side_effect=fake_app,
        ), patch("agentic_loop.server.ThreadingHTTPServer", FakeServer), patch(
            "agentic_loop.server.ensure_ollama_model_available",
            return_value=True,
        ):
            exit_code = serve_command(
                [
                    "--port",
                    "0",
                    "--voice-provider",
                    "gemini-live",
                    "--voice-model",
                    "test-live-model",
                ]
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(created_apps[0]["voice_provider"], "gemini-live")
        self.assertEqual(created_apps[0]["voice_model"], "test-live-model")

    def test_serve_accepts_learning_flags(self):
        created_apps = []

        class FakeServer:
            def __init__(self, address, handler):
                self.address = address
                self.handler = handler

            def serve_forever(self):
                return None

        def fake_app(**kwargs):
            created_apps.append(kwargs)
            return object()

        with redirect_stdout(StringIO()), patch(
            "agentic_loop.server.AgentServerApp",
            side_effect=fake_app,
        ), patch("agentic_loop.server.ThreadingHTTPServer", FakeServer), patch(
            "agentic_loop.server.ensure_ollama_model_available",
            return_value=True,
        ):
            exit_code = serve_command(
                [
                    "--port",
                    "0",
                    "--learning",
                    "off",
                    "--learning-threshold",
                    "5",
                ]
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(created_apps[0]["learning_mode"], "off")
        self.assertEqual(created_apps[0]["learning_threshold"], 5)

    def test_server_learning_and_skill_methods(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = AgentServerApp(
                workspace=str(SAMPLE_WORKSPACE),
                db_path=str(Path(tmp) / "agentic.db"),
            )
            markdown = render_skill_markdown(
                key="release-checklist",
                title="Release Checklist",
                description="Prepare releases safely.",
                triggers=["release", "push"],
                procedure=["Run tests.", "Push the intended branch."],
            )
            draft = app.storage.create_learning_draft(
                "skill",
                "Release Checklist",
                "release-checklist",
                {
                    "key": "release-checklist",
                    "title": "Release Checklist",
                    "description": "Prepare releases safely.",
                    "triggers": ["release", "push"],
                    "markdown": markdown,
                    "source_run_ids": ["run_release"],
                },
                source_run_id="run_release",
            )

            listed = app.learning_drafts()
            approved = app.approve_learning_draft(draft["id"])
            archived = app.archive_skill("release-checklist")

            self.assertEqual(listed[0]["id"], draft["id"])
            self.assertEqual(approved["skill"]["key"], "release-checklist")
            self.assertIn("## Procedure", app.skill("release-checklist")["markdown"])
            self.assertEqual(archived["status"], "archived")

    def test_learning_http_routes_without_network_socket(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = AgentServerApp(
                workspace=str(SAMPLE_WORKSPACE),
                db_path=str(Path(tmp) / "agentic.db"),
            )
            markdown = render_skill_markdown(
                key="release-checklist",
                title="Release Checklist",
                description="Prepare releases safely.",
                triggers=["release"],
                procedure=["Run tests."],
            )
            draft = app.storage.create_learning_draft(
                "skill",
                "Release Checklist",
                "release-checklist",
                {
                    "key": "release-checklist",
                    "title": "Release Checklist",
                    "description": "Prepare releases safely.",
                    "triggers": ["release"],
                    "markdown": markdown,
                },
                source_run_id="run_release",
            )
            handler_cls = make_handler(app)

            drafts = self._call_handler_get(handler_cls, "/learning/drafts")
            approved = self._call_handler_post(
                handler_cls,
                "/learning/drafts/approve",
                {"id": draft["id"]},
            )
            skill = self._call_handler_get(handler_cls, "/skills/release-checklist")
            archived = self._call_handler_post(
                handler_cls,
                "/skills/archive",
                {"key": "release-checklist"},
            )

            self.assertEqual(drafts["payload"]["drafts"][0]["id"], draft["id"])
            self.assertEqual(approved["payload"]["skill"]["key"], "release-checklist")
            self.assertIn("## Procedure", skill["payload"]["skill"]["markdown"])
            self.assertEqual(archived["payload"]["skill"]["status"], "archived")

    def test_gemini_live_token_payloads_are_constrained(self):
        now = datetime(2026, 5, 23, 12, 0, tzinfo=timezone.utc)
        client = GeminiLiveTokenClient(
            api_key="secret",
            model="test-live-model",
            now_fn=lambda: now,
        )

        input_payload = client.token_request_payload("input")
        output_payload = client.token_request_payload("output")

        self.assertEqual(input_payload["uses"], 1)
        self.assertEqual(input_payload["expireTime"], "2026-05-23T12:30:00Z")
        self.assertEqual(input_payload["newSessionExpireTime"], "2026-05-23T12:01:00Z")
        self.assertEqual(
            input_payload["bidiGenerateContentSetup"]["model"],
            "models/test-live-model",
        )
        self.assertEqual(
            input_payload["bidiGenerateContentSetup"]["generationConfig"]["responseModalities"],
            ["TEXT"],
        )
        self.assertIn("inputAudioTranscription", input_payload["bidiGenerateContentSetup"])
        self.assertEqual(
            output_payload["bidiGenerateContentSetup"]["generationConfig"]["responseModalities"],
            ["AUDIO"],
        )
        self.assertIn("outputAudioTranscription", output_payload["bidiGenerateContentSetup"])

    def test_gemini_live_token_client_requires_api_key(self):
        with patch.dict(os.environ, {}, clear=True):
            client = GeminiLiveTokenClient()

        self.assertFalse(client.available())
        with self.assertRaises(GeminiLiveTokenError):
            client.create_token("input")

    def test_gemini_live_token_client_does_not_return_api_key(self):
        captured = {}

        class FakeResponse:
            def read(self):
                return b'{"name":"auth_tokens/test-token"}'

        def fake_urlopen(request, timeout):
            captured["url"] = request.full_url
            captured["body"] = json.loads(request.data.decode("utf-8"))
            captured["timeout"] = timeout
            return FakeResponse()

        client = GeminiLiveTokenClient(
            api_key="secret-key",
            model="test-live-model",
            urlopen_fn=fake_urlopen,
        )
        token = client.create_token("input", session_id="session-1")

        self.assertEqual(token["token"], "auth_tokens/test-token")
        self.assertEqual(token["session_id"], "session-1")
        self.assertIn("key=secret-key", captured["url"])
        self.assertNotIn("secret-key", json.dumps(token))
        self.assertIn("bidiGenerateContentSetup", captured["body"])

    def test_voice_config_falls_back_without_gemini_key(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            app = AgentServerApp(
                workspace=str(SAMPLE_WORKSPACE),
                db_path=str(Path(tmp) / "agentic.db"),
            )
            config = app.voice_config()

        self.assertFalse(config["live_available"])
        self.assertTrue(config["fallback_available"])
        self.assertEqual(config["selected_provider"], "browser-web-speech")
        self.assertIn("GEMINI_API_KEY", config["unavailable_reason"])

    def test_voice_config_and_token_creation_use_fake_token_client(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake_client = FakeGeminiTokenClient()
            app = AgentServerApp(
                workspace=str(SAMPLE_WORKSPACE),
                db_path=str(Path(tmp) / "agentic.db"),
                voice_provider="gemini-live",
                voice_model="test-live-model",
                voice_token_client=fake_client,
            )
            config = app.voice_config()
            token = app.create_voice_token("input")

        self.assertTrue(config["live_available"])
        self.assertEqual(config["selected_provider"], "gemini-live")
        self.assertEqual(token["token"], "auth_tokens/input")
        self.assertEqual(token["purpose"], "input")
        self.assertTrue(token["session_id"])
        self.assertEqual(fake_client.calls[0][0], "input")

    def test_cli_lists_model_providers(self):
        output = StringIO()
        with redirect_stdout(output):
            exit_code = cli_main(["--models"])

        text = output.getvalue()
        self.assertEqual(exit_code, 0)
        self.assertIn("ollama", text)
        self.assertIn("openai-compatible", text)
        self.assertIn("gemini", text)

    def test_install_script_exposes_ollama_setup_options(self):
        text = (REPO_ROOT / "scripts" / "install.sh").read_text(encoding="utf-8")

        self.assertIn("--with-ollama", text)
        self.assertIn("--pull-model", text)
        self.assertIn("--no-ollama", text)
        self.assertIn("--source-url", text)
        self.assertIn("AGENTIC_LOOP_OLLAMA_MODEL", text)
        self.assertIn("AGENTIC_LOOP_SOURCE_URL", text)
        self.assertIn("https://ollama.com/install.sh", text)
        self.assertIn("https://github.com/Bowen-AI/AgenticLocal/archive/refs/heads/main.tar.gz", text)
        self.assertIn("DEFAULT_INTERACTIVE_MODEL", text)

    def test_model_command_clears_stale_settings_when_provider_changes(self):
        ollama = ModelSelection.from_values(provider="ollama", model_name=DEFAULT_INTERACTIVE_MODEL)
        rule = parse_model_command("rule", fallback=ollama)
        back_to_ollama = parse_model_command("ollama", fallback=rule)

        self.assertEqual(rule.provider, "rule")
        self.assertIsNone(rule.model_name)
        self.assertEqual(back_to_ollama.provider, "ollama")
        self.assertEqual(back_to_ollama.model_name, DEFAULT_INTERACTIVE_MODEL)

    def test_ollama_model_setup_prompts_and_pulls_missing_model(self):
        lines = []
        pulled = []
        selection = ModelSelection.from_values(
            provider="ollama",
            model_name="qwen3.5:4b",
            ollama_host="http://ollama.test",
        )

        available = ensure_ollama_model_available(
            selection,
            prompt_fn=lambda prompt: "yes",
            print_fn=lines.append,
            list_models_fn=lambda host: {"qwen3.5:4b-mlx"},
            pull_model_fn=lambda model, host, print_fn: pulled.append((model, host)),
        )

        self.assertTrue(available)
        self.assertEqual(pulled, [("qwen3.5:4b", "http://ollama.test")])
        self.assertIn("Ollama model is not installed: qwen3.5:4b", lines)

    def test_ollama_model_setup_accepts_latest_tag_alias(self):
        self.assertTrue(ollama_model_installed("llama3.2", {"llama3.2:latest"}))

    def test_cli_prompts_for_explicit_missing_ollama_model_before_run(self):
        with patch("agentic_loop.cli.ensure_ollama_model_available", return_value=False) as ensure:
            exit_code = cli_main(["--provider", "ollama", "--model", "missing-model", "hello"])

        self.assertEqual(exit_code, 1)
        ensure.assert_called_once()

    def test_client_prompts_for_explicit_local_ollama_model_before_request(self):
        with patch("agentic_loop.client.ensure_ollama_model_available", return_value=False) as ensure:
            exit_code = cli_main(
                ["client", "--provider", "ollama", "--model", "missing-model", "hello"]
            )

        self.assertEqual(exit_code, 1)
        ensure.assert_called_once()

    def test_chat_prompts_for_default_missing_ollama_model_before_start(self):
        with tempfile.TemporaryDirectory() as tmp, patch(
            "agentic_loop.chat.ensure_ollama_model_available",
            return_value=False,
        ) as ensure:
            exit_code = run_chat(
                [
                    "--db",
                    str(Path(tmp) / "agentic.db"),
                ],
            )

        self.assertEqual(exit_code, 1)
        ensure.assert_called_once()

    def test_chat_prompts_for_explicit_missing_ollama_model_before_start(self):
        with tempfile.TemporaryDirectory() as tmp, patch(
            "agentic_loop.chat.ensure_ollama_model_available",
            return_value=False,
        ) as ensure:
            exit_code = run_chat(
                [
                    "--db",
                    str(Path(tmp) / "agentic.db"),
                    "--model",
                    "missing-model",
                ],
            )

        self.assertEqual(exit_code, 1)
        ensure.assert_called_once()

    def test_chat_model_switch_keeps_current_model_when_download_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = StringIO()
            with redirect_stdout(output), patch(
                "builtins.input",
                side_effect=["/model ollama missing-model", "/model", "/exit"],
            ), patch(
                "agentic_loop.chat.ensure_ollama_model_available",
                side_effect=lambda selection: selection.provider != "ollama",
            ) as ensure:
                exit_code = run_chat(
                    [
                        "--db",
                        str(Path(tmp) / "agentic.db"),
                        "--provider",
                        "rule",
                    ],
                )
            text = output.getvalue()

        self.assertEqual(exit_code, 0)
        self.assertEqual([call.args[0].provider for call in ensure.call_args_list], ["rule", "ollama"])
        self.assertIn("model: rule (none)", text)

    def test_serve_prompts_for_default_missing_ollama_model_before_start(self):
        with patch(
            "agentic_loop.server.ensure_ollama_model_available",
            return_value=False,
        ) as ensure:
            exit_code = serve_command(["--port", "0"])

        self.assertEqual(exit_code, 1)
        ensure.assert_called_once()

    def test_serve_prompts_for_explicit_missing_ollama_model_before_start(self):
        with patch(
            "agentic_loop.server.ensure_ollama_model_available",
            return_value=False,
        ) as ensure:
            exit_code = serve_command(["--port", "0", "--model", "missing-model"])

        self.assertEqual(exit_code, 1)
        ensure.assert_called_once()

    def test_chat_can_show_and_switch_models(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = StringIO()
            with redirect_stdout(output), patch(
                "builtins.input",
                side_effect=["/model", "/models", "/model rule", "/exit"],
            ):
                exit_code = run_chat(
                    [
                        "--db",
                        str(Path(tmp) / "agentic.db"),
                        "--provider",
                        "rule",
                    ],
                )
            text = output.getvalue()

            self.assertEqual(exit_code, 0)
            self.assertIn("model: rule", text)
            self.assertIn("ollama", text)

    def test_chat_supports_registered_workflow_shortcuts(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = StringIO()
            with redirect_stdout(output), patch(
                "builtins.input",
                side_effect=["/release", "/exit"],
            ):
                exit_code = run_chat(
                    [
                        "--db",
                        str(Path(tmp) / "agentic.db"),
                        "--provider",
                        "rule",
                    ],
                )
            text = output.getvalue()

            self.assertEqual(exit_code, 0)
            self.assertIn("workflow active: /release", text)

    def test_chat_learning_review_and_skill_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "agentic.db"
            storage = SQLiteStore(db_path)
            memory_draft = storage.create_learning_draft(
                "memory",
                "Remember preferred test command",
                "preferred-test-command",
                {"key": "preferred_test_command", "value": "python3 -m unittest"},
                source_run_id="run_memory",
            )
            markdown = render_skill_markdown(
                key="release-checklist",
                title="Release Checklist",
                description="Prepare releases safely.",
                triggers=["release"],
                procedure=["Run tests.", "Push the intended branch."],
            )
            storage.upsert_skill(
                key="release-checklist",
                title="Release Checklist",
                description="Prepare releases safely.",
                triggers=["release"],
                markdown=markdown,
            )
            output = StringIO()
            with redirect_stdout(output), patch(
                "builtins.input",
                side_effect=[
                    "/learn",
                    f"/learn approve {memory_draft['id']}",
                    "/skills",
                    "/skill release-checklist",
                    "/skill archive release-checklist",
                    "/exit",
                ],
            ):
                exit_code = run_chat(
                    [
                        "--db",
                        str(db_path),
                        "--provider",
                        "rule",
                    ],
                )
            text = output.getvalue()

            self.assertEqual(exit_code, 0)
            self.assertIn("Remember preferred test command", text)
            self.assertIn(f"approved learning draft {memory_draft['id']}", text)
            self.assertIn("release-checklist - Release Checklist", text)
            self.assertIn("## Procedure", text)
            self.assertIn("archived skill release-checklist", text)

    def test_voice_adapter_interface_can_be_mocked(self):
        browser = BrowserSpeechVoiceAdapter()
        gemini = GeminiLiveVoiceAdapter("test-live-model")
        realtime = RealtimeVoiceAdapterSpec("gemini-live")

        self.assertIsInstance(browser, VoiceAdapter)
        self.assertIsInstance(gemini, VoiceAdapter)
        self.assertFalse(browser.describe().realtime)
        self.assertEqual(gemini.describe().name, "gemini-live")
        self.assertTrue(realtime.describe().realtime)

    def test_network_tools_are_opt_in(self):
        self.assertNotIn("search_web", create_default_tools().names())
        self.assertIn("search_web", create_default_tools(enable_network=True).names())

    def test_network_tool_handlers_parse_results(self):
        tools = create_default_tools(enable_network=True)
        context = ToolContext(workspace_root=SAMPLE_WORKSPACE, web_client=FakeWebClient())

        web = tools.run("search_web", context, {"query": "agentic ai"})
        news = tools.run("search_news", context, {"query": "agentic ai"})
        page = tools.run("fetch_url", context, {"url": "https://example.test/page"})

        self.assertEqual(web["results"][0]["title"], "Agentic AI")
        self.assertEqual(news["results"][0]["source"], "Example News")
        self.assertEqual(page["title"], "Example Page")

    def test_interactive_planner_can_search_news(self):
        result = self.make_network_controller().run("Search news about agentic AI.")

        self.assertEqual(result.state.steps[0].tool_name, "search_news")
        self.assertEqual(result.state.steps[0].observation["query"], "agentic ai")
        self.assertIn("Example News", json.dumps(result.state.steps[0].observation))
        self.assertIn("Google News RSS", result.final_answer)

    def test_interactive_planner_handles_news_typos(self):
        result = self.make_network_controller().run("what is thenews today")

        self.assertEqual(result.state.steps[0].tool_name, "search_news")
        self.assertEqual(result.state.steps[0].observation["query"], "top stories")
        self.assertIn("Google News RSS", result.final_answer)

    def test_repeated_identical_tool_call_finalizes_from_prior_result(self):
        model = ScriptedModel(
            [
                ModelResponse.call(
                    "search_news",
                    {"query": "top stories", "max_results": 5},
                    "call_news_1",
                ),
                ModelResponse.call(
                    "search_news",
                    {"query": "top stories", "max_results": 5},
                    "call_news_2",
                ),
            ]
        )
        result = self.make_network_controller(model=model).run("Tell me today's top news.")

        tool_calls = [step for step in result.state.steps if step.action == "tool_call"]
        self.assertEqual(len(tool_calls), 1)
        self.assertEqual(result.state.steps[-1].action, "repeated_tool_finalized")
        self.assertNotEqual(result.final_answer, "Agent stopped because the step limit was reached.")
        self.assertIn("Google News RSS", result.final_answer)

    def test_interactive_planner_can_search_web(self):
        result = self.make_network_controller().run("Search the internet for agentic AI.")

        self.assertEqual(result.state.steps[0].tool_name, "search_web")
        self.assertEqual(result.state.steps[0].observation["query"], "agentic ai")
        self.assertIn("Agentic AI", result.final_answer)

    def test_voice_page_embeds_chat_voice_controls(self):
        html = voice_page_html("0.1.0")

        self.assertIn("agentic-loop voice", html)
        self.assertIn("Connect live", html)
        self.assertIn("Mute", html)
        self.assertIn("Interrupt", html)
        self.assertIn("SpeechRecognition", html)
        self.assertIn("speechSynthesis", html)
        self.assertIn("new WebSocket", html)
        self.assertIn("AudioContext", html)
        self.assertIn("realtimeInput", html)
        self.assertIn("audio/pcm;rate=16000", html)
        self.assertIn("EventSource", html)
        self.assertIn('fetch("/voice/config"', html)
        self.assertIn('fetch("/voice/gemini/token"', html)
        self.assertIn('fetch("/sessions"', html)
        self.assertIn('fetch("/chat"', html)
        self.assertIn('"/events?follow=1', html)
        self.assertIn('fetch("/registry/rules"', html)
        self.assertIn('fetch("/workflows/start"', html)
        self.assertIn("Tool timeline", html)
        self.assertIn("Rules", html)
        self.assertIn("Workflows", html)


if __name__ == "__main__":
    unittest.main()
