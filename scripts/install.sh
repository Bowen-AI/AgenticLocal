#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

INSTALL_DIR="${AGENTIC_LOOP_INSTALL_DIR:-$HOME/.local/share/agentic-loop}"
BIN_DIR="${AGENTIC_LOOP_BIN_DIR:-$HOME/.local/bin}"
VENV_DIR="$INSTALL_DIR/venv"

python3 - <<'PY'
import sys

if sys.version_info < (3, 11):
    raise SystemExit("agentic-loop requires Python 3.11 or newer")
PY

mkdir -p "$INSTALL_DIR" "$BIN_DIR"

if python3 -m venv "$VENV_DIR" >/dev/null 2>&1; then
  "$VENV_DIR/bin/python" -m pip install --upgrade "$PWD"
  cat > "$BIN_DIR/agentic-loop" <<EOF
#!/usr/bin/env sh
exec "$VENV_DIR/bin/agentic-loop" "\$@"
EOF
  chmod +x "$BIN_DIR/agentic-loop"
  echo "agentic-loop installed at $BIN_DIR/agentic-loop"
  echo "Make sure $BIN_DIR is on PATH."
  "$BIN_DIR/agentic-loop" --version
  exit 0
fi

if python3 -m pip --version >/dev/null 2>&1; then
  python3 -m pip install --user --upgrade "$PWD"
  echo "agentic-loop installed with pip --user."
  echo "Make sure $BIN_DIR is on PATH."
  python3 -m agentic_loop --version
  exit 0
fi

cat >&2 <<'EOF'
Could not create a virtual environment and python3 -m pip is unavailable.

Install Python venv/pip support, then run scripts/install.sh again:

  macOS with Homebrew:
    brew install python

  Debian/Ubuntu:
    sudo apt install python3-venv python3-pip

  Fedora:
    sudo dnf install python3 python3-pip

  Alpine:
    sudo apk add python3 py3-pip
EOF
exit 1
