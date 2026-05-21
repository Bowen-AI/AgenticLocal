import json
import shutil
import subprocess
import sys
import tempfile
import textwrap
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agentic_loop import BrowserSpeechVoiceAdapter, RealtimeVoiceAdapterSpec
from agentic_loop.factory import create_controller
from agentic_loop.server import AgentServerApp, make_handler


REPO_ROOT = Path(__file__).resolve().parents[1]


def section(title: str) -> None:
    print()
    print(f"== {title} ==")


def run_cli(args: list[str]) -> str:
    completed = subprocess.run(
        [sys.executable, "-m", "agentic_loop", *args],
        cwd=REPO_ROOT,
        check=True,
        text=True,
        capture_output=True,
    )
    return completed.stdout.strip()


def post_json(url: str, payload: dict) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def get_text(url: str) -> str:
    with urllib.request.urlopen(url, timeout=5) as response:
        return response.read().decode("utf-8")


def make_workspace(tmp: Path) -> Path:
    workspace = tmp / "workspace"
    shutil.copytree(REPO_ROOT / "sample_workspace", workspace)
    return workspace


def cli_showcase(tmp: Path) -> None:
    workspace = make_workspace(tmp)
    db = tmp / "cli-showcase.db"

    section("CLI reads and dataset inspection")
    listed = run_cli(["--workspace", str(workspace), "--db", str(db), "List files in the workspace."])
    inspected = json.loads(
        run_cli(
            [
                "--workspace",
                str(workspace),
                "--db",
                str(db),
                "Inspect data/sample.csv as a dataset.",
                "--json",
            ]
        )
    )
    print(listed)
    print(
        "inspect_csv:",
        inspected["steps"][0]["observation"]["rows"],
        "rows, columns:",
        ", ".join(inspected["steps"][0]["observation"]["columns"]),
    )
    assert "data/sample.csv" in listed
    assert inspected["steps"][0]["tool_name"] == "inspect_csv"

    section("SQLite memory across separate CLI runs")
    remembered = run_cli(
        ["--workspace", str(workspace), "--db", str(db), "Remember project language is python."]
    )
    recalled = run_cli(
        ["--workspace", str(workspace), "--db", str(db), "What is the project language?"]
    )
    print(remembered)
    print(recalled)
    assert remembered == "I remembered project_language."
    assert "project_language=python" in recalled

    section("Default write root")
    wrote = run_cli(
        ["--workspace", str(workspace), "--db", str(db), "Write a note saying hello from the agent."]
    )
    output_file = workspace / "outputs" / "agent_note.txt"
    print(wrote)
    print(f"created: {output_file.relative_to(workspace)} -> {output_file.read_text(encoding='utf-8')}")
    assert output_file.exists()

    section("Additional named write root")
    draft = json.loads(
        run_cli(
            [
                "--workspace",
                str(workspace),
                "--db",
                str(db),
                "--write-root",
                "drafts",
                "Write a draft note.",
                "--scripted-tool-call",
                '{"name":"write_file","arguments":{"path":"drafts/note.txt","content":"hello drafts"}}',
                "--scripted-final",
                "Draft saved.",
                "--json",
            ]
        )
    )
    draft_file = workspace / "drafts" / "note.txt"
    print("allowed:", draft["steps"][0]["allowed"], "path:", draft["steps"][0]["observation"]["path"])
    print(f"created: {draft_file.relative_to(workspace)} -> {draft_file.read_text(encoding='utf-8')}")
    assert draft_file.exists()

    section("Denied write outside configured roots")
    denied = json.loads(
        run_cli(
            [
                "--workspace",
                str(workspace),
                "--db",
                str(db),
                "Try to overwrite raw data.",
                "--scripted-tool-call",
                '{"name":"write_file","arguments":{"path":"data/raw_overwrite.txt","content":"bad"}}',
                "--scripted-final",
                "Denied.",
                "--json",
            ]
        )
    )
    print(denied["steps"][0]["action"], "-", denied["steps"][0]["observation"])
    assert denied["steps"][0]["allowed"] is False
    assert not (workspace / "data" / "raw_overwrite.txt").exists()

    section("Approval-required root")
    approval = json.loads(
        run_cli(
            [
                "--workspace",
                str(workspace),
                "--db",
                str(db),
                "--write-root",
                "reviewed",
                "--approval-root",
                "reviewed",
                "Write a reviewed note.",
                "--scripted-tool-call",
                '{"name":"write_file","arguments":{"path":"reviewed/note.txt","content":"needs review"}}',
                "--scripted-final",
                "Approval requested.",
                "--json",
            ]
        )
    )
    print(approval["steps"][0]["action"], "-", approval["steps"][0]["observation"])
    assert approval["steps"][0]["action"] == "approval_required"
    assert not (workspace / "reviewed" / "note.txt").exists()


def http_showcase(tmp: Path) -> None:
    workspace = make_workspace(tmp)
    db = tmp / "server-showcase.db"
    app = AgentServerApp(workspace=str(workspace), db_path=str(db), write_roots=["outputs", "drafts"])
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"

        section("HTTP health, voice page, and chat session")
        health = get_json(f"{base}/health")
        voice = get_text(f"{base}/voice")
        first = post_json(f"{base}/chat", {"message": "Remember project language is python."})
        second = post_json(
            f"{base}/chat",
            {"session_id": first["session_id"], "message": "What is the project language?"},
        )
        print("health:", health)
        print("voice page has SpeechRecognition:", "SpeechRecognition" in voice)
        print("session:", first["session_id"])
        print("turns:", len(second["transcript"]), "answer:", second["final_answer"])
        assert health["ok"] is True
        assert "project_language=python" in second["final_answer"]

        section("HTTP one-shot run")
        run = post_json(f"{base}/run", {"message": "Inspect data/sample.csv as a dataset."})
        print("run_id:", run["run_id"])
        print("answer:", run["final_answer"])
        assert "4 row(s)" in run["final_answer"]

        section("Durable API views")
        sessions = get_json(f"{base}/sessions")
        memory = get_json(f"{base}/memory")
        tools = get_json(f"{base}/registry/tools")
        ui = get_json(f"{base}/registry/ui")
        print("sessions:", len(sessions["sessions"]))
        print("memory records:", [item["key"] for item in memory["records"]])
        print("tools:", ", ".join(item["name"] for item in tools["tools"][:4]))
        print("ui components:", ", ".join(item["component"] for item in ui["components"][:5]))
        assert sessions["sessions"]
        assert any(item["key"] == "project_language" for item in memory["records"])
        assert any(item["name"] == "write_file" for item in tools["tools"])
        assert any(item["component"] == "table_preview" for item in ui["components"])

        section("SSE event snapshot and follow mode")
        events = get_text(f"{base}/events?session_id={first['session_id']}")
        follow = get_text(f"{base}/events?session_id={first['session_id']}&follow=1&timeout=0.2")
        event_lines = [line for line in events.splitlines() if line.startswith("event: ")]
        print("\n".join(event_lines[:8]))
        print("follow stream bytes:", len(follow), "contains final answer event:", "event: final_answer" in follow)
        assert "event: run_started" in events
        assert "event: tool_result" in events
        assert "event: final_answer" in events
        assert "event: final_answer" in follow
    finally:
        server.shutdown()
        server.server_close()


def adapter_showcase() -> None:
    section("Provider and voice adapter surfaces")
    localai = create_controller(provider="localai", model_name="demo-model", db_path=None)
    openai_compatible = create_controller(
        provider="openai-compatible",
        model_name="demo-model",
        api_base="http://127.0.0.1:9999/v1",
        db_path=None,
    )
    browser_voice = BrowserSpeechVoiceAdapter().describe()
    realtime_voice = RealtimeVoiceAdapterSpec("gemini-live").describe()
    print("model adapters:", type(localai.model).__name__, type(openai_compatible.model).__name__)
    print("browser voice:", browser_voice.name, "realtime:", browser_voice.realtime)
    print("realtime voice example:", realtime_voice.name, realtime_voice.provider_examples)
    assert type(localai.model).__name__ == "LocalAIChatModel"
    assert type(openai_compatible.model).__name__ == "OpenAICompatibleChatModel"
    assert realtime_voice.realtime is True


def main() -> None:
    print("AgenticLocal end-to-end showcase")
    print(textwrap.fill("This script demonstrates the refined architecture with real CLI runs, durable SQLite state, policy enforcement, HTTP endpoints, SSE events, registries, and adapter boundaries.", width=88))
    with tempfile.TemporaryDirectory() as raw_tmp:
        tmp = Path(raw_tmp)
        cli_showcase(tmp / "cli")
        http_showcase(tmp / "http")
        adapter_showcase()
    print()
    print("Showcase passed.")


if __name__ == "__main__":
    main()
