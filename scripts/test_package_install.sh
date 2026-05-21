#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

python3 scripts/package_release.py

python3 - <<'PY'
from pathlib import Path
import tarfile
import zipfile

dist = Path("dist")
wheels = sorted(dist.glob("agentic_loop-*-py3-none-any.whl"))
sdists = sorted(dist.glob("agentic-loop-*.tar.gz"))
assert wheels, "missing wheel artifact"
assert sdists, "missing source tarball artifact"

with zipfile.ZipFile(wheels[-1]) as archive:
    names = set(archive.namelist())
    assert "agentic_loop/cli.py" in names
    assert any(name.endswith(".dist-info/METADATA") for name in names)
    entry_points = [name for name in names if name.endswith(".dist-info/entry_points.txt")]
    assert entry_points, "missing wheel entry_points.txt"
    text = archive.read(entry_points[0]).decode("utf-8")
    assert "agentic-loop = agentic_loop.cli:main" in text

with tarfile.open(sdists[-1], "r:gz") as archive:
    names = set(archive.getnames())
    assert any(name.endswith("/pyproject.toml") for name in names)
    assert any(name.endswith("/agentic_loop/cli.py") for name in names)
    assert any(name.endswith("/tests/test_agentic_loop.py") for name in names)
PY

TMPDIR_ROOT="${TMPDIR:-/tmp}"
VENV_DIR="$(mktemp -d "$TMPDIR_ROOT/agentic-loop-install-test.XXXXXX")"
cleanup() {
  rm -rf "$VENV_DIR"
}
trap cleanup EXIT

if ! python3 -m venv "$VENV_DIR/venv" >/dev/null 2>&1; then
  if [ "${REQUIRE_VENV:-0}" = "1" ]; then
    echo "python3 -m venv is required for package install testing" >&2
    exit 1
  fi
  echo "Skipping wheel install smoke test because python3 -m venv is unavailable."
  exit 0
fi

WHEEL="$(ls dist/agentic_loop-*-py3-none-any.whl | tail -n 1)"
"$VENV_DIR/venv/bin/python" -m pip install "$WHEEL"
"$VENV_DIR/venv/bin/agentic-loop" --version
"$VENV_DIR/venv/bin/agentic-loop" --rules
