import json
import os
import tempfile
import unittest
from pathlib import Path

from agentic_loop import (
    AgentController,
    AgentSession,
    JsonlMemory,
    ModelResponse,
    RuleBasedModel,
    ScriptedModel,
    WorkspacePolicy,
    create_default_tools,
)
from agentic_loop.ollama_model import OllamaChatModel
from agentic_loop.server import AgentServerApp
from agentic_loop.voice import voice_page_html


REPO_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_WORKSPACE = REPO_ROOT / "sample_workspace"


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
        self.assertIn("outputs", result.state.steps[0].observation)

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
                memory_path=str(Path(tmp) / "memory.jsonl"),
                trace_path=str(Path(tmp) / "trace.jsonl"),
            )
            first = app.chat("Remember project language is python.")
            second = app.chat("What is the project language?", first["session_id"])
            one_shot = app.run_once("Inspect data/sample.csv as a dataset.")

            self.assertEqual(first["session_id"], second["session_id"])
            self.assertIn("I remembered project_language", first["final_answer"])
            self.assertIn("project_language=python", second["final_answer"])
            self.assertEqual(len(second["transcript"]), 4)
            self.assertIn("4 row(s)", one_shot["final_answer"])

    def test_voice_page_embeds_chat_voice_controls(self):
        html = voice_page_html("0.1.0")

        self.assertIn("agentic-loop voice", html)
        self.assertIn("SpeechRecognition", html)
        self.assertIn("speechSynthesis", html)
        self.assertIn('fetch("/chat"', html)
        self.assertIn("Tool timeline", html)


if __name__ == "__main__":
    unittest.main()
