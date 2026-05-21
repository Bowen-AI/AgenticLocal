#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

echo "== syntax compile =="
python3 -m compileall -q agentic_loop tests

echo "== unit tests =="
python3 -m unittest discover -s tests -v

echo "== smoke test =="
scripts/smoke_test.sh

echo "== package artifacts =="
scripts/test_package_install.sh

echo "== cli version =="
python3 -m agentic_loop --version

echo "== package metadata =="
python3 - <<'PY'
import pathlib
import tomllib
from agentic_loop import __version__

data = tomllib.loads(pathlib.Path("pyproject.toml").read_text(encoding="utf-8"))
project = data["project"]
assert project["name"] == "agentic-loop"
assert project["version"] == __version__
assert project["requires-python"] == ">=3.11"
assert data["project"]["dependencies"] == []
assert data["project"]["scripts"]["agentic-loop"] == "agentic_loop.cli:main"
PY

echo
echo "Release check passed."
