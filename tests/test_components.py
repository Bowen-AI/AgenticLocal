import tempfile
import unittest
from pathlib import Path

from agentic_loop import (
    AgentController,
    JsonlMemory,
    ModelResponse,
    ModelSelection,
    RuleBasedModel,
    RuleDefinition,
    RuleResolver,
    SQLiteStore,
    ScriptedModel,
    ToolCall,
    ToolRegistry,
    WorkspaceAccessConfig,
    WorkspacePolicy,
    WorkflowDefinition,
    create_default_tools,
)
from agentic_loop.context import ContextBuilder
from agentic_loop.factory import create_controller
from agentic_loop.model_selection import (
    DEFAULT_INTERACTIVE_MODEL,
    ModelSelection,
    parse_model_command,
    provider_registry,
    render_model_selection,
)
from agentic_loop.server import AgentServerApp, serialize_result
from agentic_loop.tools import Tool, ToolContext
from agentic_loop.types import AgentState, AgentStep, Message


REPO_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_WORKSPACE = REPO_ROOT / "sample_workspace"


class ComponentCoverageTest(unittest.TestCase):
    def make_controller(self, model=None, memory=None, storage=None, workspace=None, max_steps=8):
        workspace = Path(workspace or SAMPLE_WORKSPACE)
        return AgentController(
            model=model or RuleBasedModel(),
            tools=create_default_tools(),
            policy=WorkspacePolicy(workspace),
            workspace_root=workspace,
            memory=memory,
            storage=storage,
            max_steps=max_steps,
        )

    def test_jsonl_memory_preserves_order_and_latest_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory = JsonlMemory(Path(tmp) / "memory.jsonl")

            memory.remember("home_location", "LA")
            memory.remember("favorite_color", "green")
            memory.remember("home_location", "Los Angeles")

            self.assertEqual([record.key for record in memory.all()], [
                "home_location",
                "favorite_color",
                "home_location",
            ])
            self.assertEqual(memory.latest("home_location").value, "Los Angeles")
            self.assertIsNone(memory.latest("missing"))

    def test_jsonl_memory_searches_keys_and_structured_values_with_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory = JsonlMemory(Path(tmp) / "memory.jsonl")
            memory.remember("project", {"name": "AgenticLocal", "language": "python"})
            memory.remember("note", "Python smoke test")
            memory.remember("other", "not relevant")
            memory.remember("preference", {"topic": "python packaging"})

            matches = memory.search("python", limit=2)

            self.assertEqual([record.key for record in matches], ["note", "preference"])
            self.assertEqual(matches[-1].value["topic"], "python packaging")

    def test_sqlite_memory_preserves_order_and_latest_across_reopen(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "agentic.db"
            memory = SQLiteStore(db_path)
            memory.remember("home_location", "LA")
            memory.remember("home_location", "Los Angeles")

            reopened = SQLiteStore(db_path)

            self.assertEqual(reopened.latest("home_location").value, "Los Angeles")
            self.assertEqual([record.value for record in reopened.all()], ["LA", "Los Angeles"])

    def test_sqlite_memory_searches_case_insensitively_and_limits_latest(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory = SQLiteStore(Path(tmp) / "agentic.db")
            memory.remember("one", "Python one")
            memory.remember("two", "python two")
            memory.remember("three", "PYTHON three")

            matches = memory.search("python", limit=2)

            self.assertEqual([record.key for record in matches], ["two", "three"])

    def test_remember_tool_requires_memory_context(self):
        tools = create_default_tools()
        context = ToolContext(workspace_root=SAMPLE_WORKSPACE)

        with self.assertRaisesRegex(RuntimeError, "memory is not configured"):
            tools.run("remember", context, {"key": "home_location", "value": "LA"})

    def test_remember_and_recall_tools_round_trip_structured_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            tools = create_default_tools()
            memory = SQLiteStore(Path(tmp) / "agentic.db")
            context = ToolContext(workspace_root=SAMPLE_WORKSPACE, memory=memory)

            written = tools.run(
                "remember",
                context,
                {"key": "profile", "value": {"city": "LA", "timezone": "Pacific"}},
            )
            recalled = tools.run("recall", context, {"query": "Pacific"})

            self.assertEqual(written["key"], "profile")
            self.assertEqual(recalled["records"][0]["value"]["city"], "LA")

    def test_plain_personal_fact_is_not_persisted_without_remember(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory = SQLiteStore(Path(tmp) / "agentic.db")
            result = self.make_controller(memory=memory).run("I live in LA.")

            self.assertEqual(memory.all(), [])
            self.assertNotEqual(result.state.steps[0].tool_name if result.state.steps else None, "remember")

    def test_remember_personal_fact_currently_saves_generic_note(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory = SQLiteStore(Path(tmp) / "agentic.db")
            result = self.make_controller(memory=memory).run("Remember that I live in LA.")

            self.assertIn("I remembered note", result.final_answer)
            self.assertEqual(memory.latest("note").value, "Remember that I live in LA.")

    def test_memory_write_emits_memory_event_when_storage_logger_is_used(self):
        with tempfile.TemporaryDirectory() as tmp:
            controller = create_controller(
                workspace=SAMPLE_WORKSPACE,
                db_path=Path(tmp) / "agentic.db",
                provider="rule",
            )

            result = controller.run("Remember project language is python.", session_id="s1")
            events = controller.storage.events_after(session_id="s1")

            self.assertIn("I remembered project_language", result.final_answer)
            self.assertIn("memory_written", [event["event_type"] for event in events])

    def test_context_builder_includes_matching_memory_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory = JsonlMemory(Path(tmp) / "memory.jsonl")
            memory.remember("home_location", "LA")
            memory.remember("favorite_color", "green")
            state = AgentState(goal="home_location")

            content = ContextBuilder().state_message(state, memory).content

            self.assertIn("home_location", content)
            self.assertIn('"LA"', content)
            self.assertNotIn("favorite_color", content)

    def test_context_builder_includes_active_rule_prompt_text(self):
        rule = RuleDefinition(
            key="academic",
            label="Academic",
            description="Formal style",
            category="style",
            prompt_text="Use careful sourcing language.",
        )
        state = AgentState(goal="Explain this.")

        content = ContextBuilder().state_message(state, active_rules=[rule]).content

        self.assertIn("Active rules:", content)
        self.assertIn("academic", content)
        self.assertIn("Use careful sourcing language.", content)

    def test_tool_registry_rejects_duplicate_tools_and_unknown_runs(self):
        registry = ToolRegistry()
        tool = Tool(
            name="noop",
            description="No operation",
            parameters={"type": "object", "properties": {}, "required": []},
            handler=lambda context, arguments: {"ok": True},
        )
        registry.register(tool)

        with self.assertRaisesRegex(ValueError, "tool already registered"):
            registry.register(tool)
        with self.assertRaisesRegex(KeyError, "unknown tool"):
            registry.run("missing", ToolContext(workspace_root=SAMPLE_WORKSPACE), {})

    def test_default_tool_metadata_has_ui_and_risk_hints(self):
        metadata = {item["name"]: item for item in create_default_tools(enable_network=True).metadata()}

        self.assertEqual(metadata["inspect_csv"]["ui_component_hint"], "table_preview")
        self.assertEqual(metadata["write_file"]["risk_level"], "medium")
        self.assertIn("search_news", metadata)

    def test_workspace_access_config_rejects_roots_outside_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "read root escapes workspace"):
                WorkspaceAccessConfig(Path(tmp) / "workspace", read_roots=("../outside",))

    def test_workspace_policy_read_roots_are_enforced(self):
        policy = WorkspacePolicy(SAMPLE_WORKSPACE, read_roots=("data",))

        allowed = policy.check(ToolCall("read_file", {"path": "data/sample.csv"}))
        denied = policy.check(ToolCall("read_file", {"path": "notes/example.txt"}))

        self.assertTrue(allowed.allowed)
        self.assertFalse(denied.allowed)
        self.assertIn("configured read roots", denied.reason)

    def test_workspace_policy_denies_disallowed_tool_before_path_checks(self):
        policy = WorkspacePolicy(SAMPLE_WORKSPACE, allowed_tools={"read_file"})

        decision = policy.check(ToolCall("write_file", {"path": "../bad.txt", "content": "x"}))

        self.assertFalse(decision.allowed)
        self.assertIn("tool is not allowed", decision.reason)

    def test_rule_resolver_accepts_workflow_key_or_command(self):
        resolver = RuleResolver()

        by_key = resolver.workflow("release")
        by_command = resolver.workflow("/release")

        self.assertIsNotNone(by_key)
        self.assertEqual(by_key, by_command)
        self.assertEqual(by_key.command, "/release")

    def test_rule_resolver_precedence_run_override_beats_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = SQLiteStore(Path(tmp) / "agentic.db")
            storage.seed_default_rule_registry()
            storage.set_rule_enabled("max_effort", True, scope_type="global")
            storage.set_rule_enabled("max_effort", False, scope_type="session", scope_id="s1")
            storage.set_rule_enabled("max_effort", True, scope_type="run", scope_id="r1")
            resolver = RuleResolver(storage)

            session_rules = {rule.key for rule in resolver.active_rules(session_id="s1")}
            run_rules = {rule.key for rule in resolver.active_rules(session_id="s1", run_id="r1")}

            self.assertNotIn("max_effort", session_rules)
            self.assertIn("max_effort", run_rules)

    def test_rule_resolver_explicit_disable_beats_workflow_enabled_rule(self):
        resolver = RuleResolver()
        workflow = resolver.workflow("release")

        active = resolver.active_rules(workflow=workflow, disabled_rule_keys={"safe_writes"})
        active_keys = {rule.key for rule in active}

        self.assertIn("max_effort", active_keys)
        self.assertNotIn("safe_writes", active_keys)

    def test_workflow_definition_round_trips_optional_fields(self):
        workflow = WorkflowDefinition.from_dict(
            {
                "key": "custom",
                "description": "Custom workflow",
                "rule_keys": ["concise"],
                "max_steps_override": 3,
                "required_tools": ["read_file"],
                "prompt_prefix": "Do the custom thing.",
                "enabled": False,
            }
        )

        payload = workflow.to_dict()

        self.assertEqual(workflow.command, "/custom")
        self.assertFalse(payload["enabled"])
        self.assertEqual(payload["rule_keys"], ["concise"])

    def test_model_selection_payload_redacts_secrets_by_default(self):
        selection = ModelSelection.from_values(
            provider="openai",
            model_name="gpt-test",
            api_key="secret-key",
        )

        public_payload = selection.to_dict()
        secret_payload = selection.to_dict(include_secret=True)

        self.assertTrue(public_payload["api_key_configured"])
        self.assertNotIn("api_key", public_payload)
        self.assertEqual(secret_payload["api_key"], "secret-key")

    def test_parse_model_command_supports_keyword_form_and_rendering(self):
        selection = parse_model_command(
            "provider=openai-compatible model=remote api_base=https://example.test/v1 api_key=key"
        )

        self.assertEqual(selection.provider, "openai-compatible")
        self.assertEqual(selection.model_name, "remote")
        self.assertEqual(selection.api_base, "https://example.test/v1")
        self.assertEqual(render_model_selection(selection), "openai-compatible remote")

    def test_provider_registry_returns_copies(self):
        registry = provider_registry()
        registry[0]["provider"] = "mutated"

        self.assertEqual(provider_registry()[0]["provider"], "rule")

    def test_storage_events_filter_by_session_and_after_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = SQLiteStore(Path(tmp) / "agentic.db")
            first = storage.record_event("one", {}, session_id="a")
            storage.record_event("two", {}, session_id="b")
            third = storage.record_event("three", {}, session_id="a")

            events = storage.events_after(session_id="a", after_id=first["id"])

            self.assertEqual([event["id"] for event in events], [third["id"]])

    def test_storage_session_messages_preserve_order_and_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = SQLiteStore(Path(tmp) / "agentic.db")
            storage.append_message("s1", Message(role="user", content="hello"))
            storage.append_message(
                "s1",
                Message(role="tool", content="{}", name="read_file", tool_call_id="call_1"),
            )

            messages = storage.load_messages("s1")

            self.assertEqual([message.role for message in messages], ["user", "tool"])
            self.assertEqual(messages[1].name, "read_file")
            self.assertEqual(messages[1].tool_call_id, "call_1")

    def test_server_memory_records_exposes_persisted_memory(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = AgentServerApp(
                workspace=str(SAMPLE_WORKSPACE),
                db_path=str(Path(tmp) / "agentic.db"),
                provider="rule",
            )
            app.run_once("Remember project language is python.")

            records = app.memory_records()

            self.assertEqual(records[0]["key"], "project_language")
            self.assertEqual(records[0]["value"], "python")

    def test_server_model_registry_reports_default_qwen_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = AgentServerApp(
                workspace=str(SAMPLE_WORKSPACE),
                db_path=str(Path(tmp) / "agentic.db"),
                provider="ollama",
                model_name=DEFAULT_INTERACTIVE_MODEL,
            )

            registry = app.model_registry()

            self.assertEqual(registry["default"]["provider"], "ollama")
            self.assertEqual(registry["default"]["model"], DEFAULT_INTERACTIVE_MODEL)

    def test_serialize_result_includes_model_when_supplied(self):
        result = self.make_controller().run("hello")
        selection = ModelSelection.from_values(provider="rule")

        payload = serialize_result(result, selection)

        self.assertEqual(payload["model"]["provider"], "rule")
        self.assertIn("steps", payload)

    def test_agent_state_summary_limits_to_recent_steps(self):
        state = AgentState(goal="test")
        for index in range(1, 8):
            state.add_step(AgentStep(index=index, action="tool_call", tool_name=f"tool_{index}"))

        summary = state.summary(max_steps=3)

        self.assertNotIn("tool_4", summary)
        self.assertIn("tool_5", summary)
        self.assertIn("tool_7", summary)

    def test_factory_seeds_registries_when_sqlite_storage_is_enabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            controller = create_controller(
                workspace=SAMPLE_WORKSPACE,
                db_path=Path(tmp) / "agentic.db",
                provider="rule",
            )

            tool_names = {item["name"] for item in controller.storage.list_tool_registry()}
            workflows = {item["key"] for item in controller.storage.list_workflow_registry()}

            self.assertIn("inspect_csv", tool_names)
            self.assertIn("release", workflows)

    def test_factory_can_use_legacy_jsonl_memory_over_sqlite_memory(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory_path = Path(tmp) / "memory.jsonl"
            db_path = Path(tmp) / "agentic.db"
            controller = create_controller(
                workspace=SAMPLE_WORKSPACE,
                memory_path=memory_path,
                db_path=db_path,
                provider="rule",
            )

            controller.run("Remember project language is python.")

            self.assertEqual(JsonlMemory(memory_path).latest("project_language").value, "python")
            self.assertEqual(SQLiteStore(db_path).all(), [])

    def test_scripted_model_responses_are_consumed_in_order(self):
        model = ScriptedModel(
            [
                ModelResponse.call("list_files", {"path": "."}, "call_1"),
                ModelResponse.final("done"),
            ]
        )

        result = self.make_controller(model=model).run("List then stop")

        self.assertEqual(result.state.steps[0].tool_name, "list_files")
        self.assertEqual(result.final_answer, "done")

