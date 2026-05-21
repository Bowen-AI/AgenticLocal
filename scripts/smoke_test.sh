#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

DB_FILE="${TMPDIR:-/tmp}/agentic-loop-smoke.db"
TRACE_FILE="${TMPDIR:-/tmp}/agentic-loop-smoke-trace.jsonl"

DB_FILE="$DB_FILE" TRACE_FILE="$TRACE_FILE" python3 - <<'PY'
import os
from pathlib import Path

for path in [
    Path(os.environ["DB_FILE"]),
    Path(os.environ["DB_FILE"] + "-wal"),
    Path(os.environ["DB_FILE"] + "-shm"),
    Path(os.environ["TRACE_FILE"]),
    Path("sample_workspace/outputs/agent_note.txt"),
]:
    if path.exists():
        path.unlink()
PY

echo "== unit tests =="
python3 -m unittest discover -s tests -v

echo
echo "== list files =="
python3 -m agentic_loop \
  "List files in the workspace." \
  --db "$DB_FILE" \
  --trace "$TRACE_FILE"

echo
echo "== model registry =="
MODELS_OUTPUT="$(python3 -m agentic_loop --models)"
echo "$MODELS_OUTPUT"
printf '%s' "$MODELS_OUTPUT" | python3 -c '
import sys
text = sys.stdin.read()
assert "rule:" in text
assert "ollama:" in text
assert "openai-compatible:" in text
assert "gemini:" in text
'

echo
echo "== inspect csv =="
INSPECT_OUTPUT="$(
  python3 -m agentic_loop \
    "Inspect data/sample.csv as a dataset." \
    --db "$DB_FILE" \
    --trace "$TRACE_FILE" \
    --json
)"
echo "$INSPECT_OUTPUT"
printf '%s' "$INSPECT_OUTPUT" | python3 -c '
import json
import sys
data = json.load(sys.stdin)
assert data["evaluation"]["has_final_answer"] is True
assert data["evaluation"]["tool_errors"] == 0
assert "4 row(s)" in data["final_answer"]
assert data["steps"][0]["tool_name"] == "inspect_csv"
'

echo
echo "== memory =="
python3 -m agentic_loop \
  "Remember project language is python." \
  --db "$DB_FILE" \
  --trace "$TRACE_FILE"
RECALL_OUTPUT="$(
  python3 -m agentic_loop \
    "What is the project language?" \
    --db "$DB_FILE" \
    --trace "$TRACE_FILE"
)"
echo "$RECALL_OUTPUT"
test "$RECALL_OUTPUT" = "I found memory: project_language=python."

echo
echo "== interactive chat =="
CHAT_TRACE_FILE="${TMPDIR:-/tmp}/agentic-loop-chat-trace.jsonl"
CHAT_DB_FILE="${TMPDIR:-/tmp}/agentic-loop-chat.db"
rm -f "$CHAT_TRACE_FILE" "$CHAT_DB_FILE" "$CHAT_DB_FILE-wal" "$CHAT_DB_FILE-shm"
CHAT_OUTPUT="$(
  printf '%s\n' \
    "Remember project language is python." \
    "What is the project language?" \
    "Inspect data/sample.csv as a dataset." \
    "/history" \
    "/exit" |
  python3 -m agentic_loop chat \
    --db "$CHAT_DB_FILE" \
    --trace "$CHAT_TRACE_FILE"
)"
echo "$CHAT_OUTPUT"
printf '%s' "$CHAT_OUTPUT" | python3 -c '
import sys
text = sys.stdin.read()
assert "agentic-loop chat" in text
assert "I remembered project_language." in text
assert "I found memory: project_language=python." in text
assert "I inspected data/sample.csv: 4 row(s)" in text
assert "assistant: I found memory: project_language=python." in text
'

echo
echo "== denied unsafe read =="
DENIED_OUTPUT="$(
  python3 -m agentic_loop \
    "Read ../secret.txt" \
    --db "$DB_FILE" \
    --trace "$TRACE_FILE" \
    --json
)"
echo "$DENIED_OUTPUT"
printf '%s' "$DENIED_OUTPUT" | python3 -c '
import json
import sys
data = json.load(sys.stdin)
assert data["evaluation"]["denied_steps"] == 1
assert "policy layer denied" in data["final_answer"]
assert data["steps"][0]["allowed"] is False
'

echo
echo "== denied unsafe write =="
DENIED_WRITE_OUTPUT="$(
  python3 -m agentic_loop \
    "Try to overwrite a raw workspace file." \
    --db "$DB_FILE" \
    --trace "$TRACE_FILE" \
    --scripted-tool-call '{"name":"write_file","arguments":{"path":"data/raw_overwrite.txt","content":"bad"}}' \
    --scripted-final "I could not complete that action because the policy layer denied it." \
    --json
)"
echo "$DENIED_WRITE_OUTPUT"
printf '%s' "$DENIED_WRITE_OUTPUT" | python3 -c '
import json
import sys
data = json.load(sys.stdin)
assert data["evaluation"]["denied_steps"] == 1
assert "policy layer denied" in data["final_answer"]
assert data["steps"][0]["tool_name"] == "write_file"
assert data["steps"][0]["allowed"] is False
assert "outputs" in data["steps"][0]["observation"]
'
test ! -f sample_workspace/data/raw_overwrite.txt

echo
echo "== write output =="
WRITE_OUTPUT="$(
  python3 -m agentic_loop \
    "Write a note saying hello from the agent." \
    --db "$DB_FILE" \
    --trace "$TRACE_FILE"
)"
echo "$WRITE_OUTPUT"
test "$WRITE_OUTPUT" = "I wrote outputs/agent_note.txt."
test -f sample_workspace/outputs/agent_note.txt
test "$(cat sample_workspace/outputs/agent_note.txt)" = "hello from the agent."

echo
echo "== trace file =="
test -s "$TRACE_FILE"
TRACE_FILE="$TRACE_FILE" python3 -c '
import json
import os
from pathlib import Path
path = Path(os.environ["TRACE_FILE"])
events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
assert any(event["event_type"] == "tool_requested" for event in events)
assert any(event["event_type"] == "tool_result" for event in events)
assert any(event["event_type"] == "final_answer" for event in events)
'

echo
echo "== cleanup =="
python3 - <<'PY'
from pathlib import Path

for path in [
    Path("sample_workspace/outputs/agent_note.txt"),
]:
    if path.exists():
        path.unlink()
PY

echo
echo "Smoke test passed."
