import json
import sys
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agentic_loop.server import AgentServerApp, make_handler


def post_json(url, payload):
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def get_json(url):
    with urllib.request.urlopen(url, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def get_text(url):
    with urllib.request.urlopen(url, timeout=5) as response:
        return response.read().decode("utf-8")


def main():
    with TemporaryDirectory() as tmp:
        app = AgentServerApp(
            workspace="sample_workspace",
            memory_path=str(Path(tmp) / "memory.jsonl"),
            trace_path=str(Path(tmp) / "trace.jsonl"),
        )
        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{server.server_address[1]}"
            health = get_json(f"{base}/health")
            voice_html = get_text(f"{base}/voice")
            first = post_json(
                f"{base}/chat",
                {"message": "Remember project language is python."},
            )
            second = post_json(
                f"{base}/chat",
                {
                    "session_id": first["session_id"],
                    "message": "What is the project language?",
                },
            )
            run = post_json(
                f"{base}/run",
                {"message": "Inspect data/sample.csv as a dataset."},
            )

            assert health["ok"] is True
            assert "agentic-loop voice" in voice_html
            assert 'fetch("/chat"' in voice_html
            assert "SpeechRecognition" in voice_html
            assert first["session_id"] == second["session_id"]
            assert "I remembered project_language" in first["final_answer"]
            assert "project_language=python" in second["final_answer"]
            assert "4 row(s)" in run["final_answer"]
            print("Server smoke test passed.")
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    main()
