import json
import os
import tempfile
import unittest
from pathlib import Path

from agentic_loop import (
    AgentController,
    AgentSession,
    BrowserSpeechVoiceAdapter,
    JsonlMemory,
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
from agentic_loop.ollama_model import OllamaChatModel
from agentic_loop.factory import create_controller
from agentic_loop.server import AgentServerApp, format_sse_events
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

        self.assertIn("Hi.", hello.final_answer)
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
            def _post(self, path, payload):
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

        response = FakeOllama().respond([], create_default_tools().schemas(), "")
        self.assertEqual(response.tool_call.name, "inspect_csv")
        self.assertEqual(response.tool_call.arguments["path"], "data/sample.csv")

    def test_ollama_model_falls_back_when_tools_not_supported(self):
        class FakeOllama(OllamaChatModel):
            def _post(self, path, payload):
                if payload.get("tools"):
                    data = {"message": {"role": "assistant", "content": "OK"}}
                    data["_retried_without_tools"] = True
                    return data
                return {"message": {"role": "assistant", "content": "OK"}}

        response = FakeOllama().respond([], create_default_tools().schemas(), "")
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

    def test_voice_adapter_interface_can_be_mocked(self):
        browser = BrowserSpeechVoiceAdapter()
        realtime = RealtimeVoiceAdapterSpec("gemini-live")

        self.assertIsInstance(browser, VoiceAdapter)
        self.assertFalse(browser.describe().realtime)
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

    def test_interactive_planner_can_search_web(self):
        result = self.make_network_controller().run("Search the internet for agentic AI.")

        self.assertEqual(result.state.steps[0].tool_name, "search_web")
        self.assertEqual(result.state.steps[0].observation["query"], "agentic ai")
        self.assertIn("Agentic AI", result.final_answer)

    def test_voice_page_embeds_chat_voice_controls(self):
        html = voice_page_html("0.1.0")

        self.assertIn("agentic-loop voice", html)
        self.assertIn("SpeechRecognition", html)
        self.assertIn("speechSynthesis", html)
        self.assertIn('fetch("/chat"', html)
        self.assertIn("Tool timeline", html)


if __name__ == "__main__":
    unittest.main()
