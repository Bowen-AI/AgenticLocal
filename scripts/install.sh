#!/usr/bin/env bash
set -euo pipefail

INSTALL_DIR="${AGENTIC_LOOP_INSTALL_DIR:-$HOME/.local/share/agentic-loop}"
BIN_DIR="${AGENTIC_LOOP_BIN_DIR:-$HOME/.local/bin}"
VENV_DIR="$INSTALL_DIR/venv"
INSTALL_OLLAMA_CHOICE="${AGENTIC_LOOP_INSTALL_OLLAMA:-prompt}"
PULL_MODEL_CHOICE="${AGENTIC_LOOP_PULL_MODEL:-prompt}"
DEFAULT_OLLAMA_MODEL="${AGENTIC_LOOP_OLLAMA_MODEL:-}"
SOURCE_URL="${AGENTIC_LOOP_SOURCE_URL:-https://github.com/Bowen-AI/AgenticLocal/archive/refs/heads/main.tar.gz}"
SOURCE_TMP_DIR=""

cleanup() {
  if [ -n "$SOURCE_TMP_DIR" ] && [ -d "$SOURCE_TMP_DIR" ]; then
    rm -rf "$SOURCE_TMP_DIR"
  fi
}
trap cleanup EXIT

usage() {
  cat <<'EOF'
Usage: scripts/install.sh [options]

Options:
  --with-ollama        Install Ollama if missing, using the official Ollama installer.
  --no-ollama          Skip Ollama install and model pull prompts.
  --pull-model         Pull the default Ollama model if missing. This is the default.
  --no-model-pull      Skip pulling the default Ollama model.
  --ollama-model NAME  Override the default Ollama model to pull.
  --source-url URL     Source archive to install when this script is not in a checkout.
  -y, --yes            Noninteractive: install Ollama if missing and pull the model.
  -h, --help           Show this help.

Environment:
  AGENTIC_LOOP_INSTALL_DIR     Package install directory.
  AGENTIC_LOOP_BIN_DIR         Command shim directory.
  AGENTIC_LOOP_INSTALL_OLLAMA  yes/no/prompt.
  AGENTIC_LOOP_PULL_MODEL      yes/no/prompt.
  AGENTIC_LOOP_OLLAMA_MODEL    Ollama model to pull.
  AGENTIC_LOOP_SOURCE_URL      Source tarball for downloaded-script installs.
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --with-ollama)
      INSTALL_OLLAMA_CHOICE="yes"
      ;;
    --no-ollama)
      INSTALL_OLLAMA_CHOICE="no"
      PULL_MODEL_CHOICE="no"
      ;;
    --pull-model)
      PULL_MODEL_CHOICE="yes"
      ;;
    --no-model-pull)
      PULL_MODEL_CHOICE="no"
      ;;
    --ollama-model)
      shift
      if [ "$#" -eq 0 ]; then
        echo "--ollama-model requires a model name" >&2
        exit 2
      fi
      DEFAULT_OLLAMA_MODEL="$1"
      ;;
    --source-url)
      shift
      if [ "$#" -eq 0 ]; then
        echo "--source-url requires a URL" >&2
        exit 2
      fi
      SOURCE_URL="$1"
      ;;
    -y|--yes)
      INSTALL_OLLAMA_CHOICE="yes"
      PULL_MODEL_CHOICE="yes"
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

python3 - <<'PY'
import sys

if sys.version_info < (3, 11):
    raise SystemExit("agentic-loop requires Python 3.11 or newer")
PY

download_source_dir() {
  SOURCE_TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/agentic-loop-source.XXXXXX")"
  archive="$SOURCE_TMP_DIR/source.tar.gz"
  echo "Downloading AgenticLocal source: $SOURCE_URL" >&2
  python3 - "$SOURCE_URL" "$archive" <<'PY'
import sys
import urllib.request

url, archive = sys.argv[1], sys.argv[2]
urllib.request.urlretrieve(url, archive)
PY
  python3 - "$archive" "$SOURCE_TMP_DIR" <<'PY'
from pathlib import Path
import os
import sys
import tarfile

archive = Path(sys.argv[1]).resolve()
destination = Path(sys.argv[2]).resolve()

with tarfile.open(archive, "r:gz") as handle:
    members = handle.getmembers()
    for member in members:
        target = (destination / member.name).resolve()
        if target != destination and destination not in target.parents:
            raise SystemExit(f"unsafe archive path: {member.name}")
    handle.extractall(destination, members)

candidates = [
    path.parent
    for path in destination.rglob("pyproject.toml")
    if (path.parent / "agentic_loop").is_dir()
]
if not candidates:
    raise SystemExit("downloaded source archive did not contain agentic_loop package")
print(candidates[0])
PY
}

source_dir_from_script() {
  script_path="${BASH_SOURCE[0]:-$0}"
  if [ -n "$script_path" ] && [ -f "$script_path" ]; then
    script_dir="$(CDPATH= cd -- "$(dirname -- "$script_path")" && pwd)"
    if [ -f "$script_dir/../pyproject.toml" ] && [ -d "$script_dir/../agentic_loop" ]; then
      (CDPATH= cd -- "$script_dir/.." && pwd)
      return 0
    fi
    if [ -f "$script_dir/pyproject.toml" ] && [ -d "$script_dir/agentic_loop" ]; then
      printf '%s\n' "$script_dir"
      return 0
    fi
  fi
  if [ -f "$PWD/pyproject.toml" ] && [ -d "$PWD/agentic_loop" ]; then
    printf '%s\n' "$PWD"
    return 0
  fi
  return 1
}

if SOURCE_DIR="$(source_dir_from_script)"; then
  :
else
  SOURCE_DIR="$(download_source_dir)"
fi
cd "$SOURCE_DIR"

if [ -z "$DEFAULT_OLLAMA_MODEL" ]; then
  DEFAULT_OLLAMA_MODEL="$(python3 - <<'PY'
from agentic_loop.model_selection import DEFAULT_INTERACTIVE_MODEL
print(DEFAULT_INTERACTIVE_MODEL)
PY
)"
fi

normalize_choice() {
  printf '%s' "$1" | tr '[:upper:]' '[:lower:]'
}

ask_yes_no() {
  prompt="$1"
  default="$2"
  if [ ! -t 0 ]; then
    [ "$default" = "yes" ]
    return
  fi
  if [ "$default" = "yes" ]; then
    suffix="[Y/n]"
  else
    suffix="[y/N]"
  fi
  while true; do
    printf '%s %s ' "$prompt" "$suffix"
    read -r answer || answer=""
    answer="$(normalize_choice "$answer")"
    if [ -z "$answer" ]; then
      [ "$default" = "yes" ]
      return
    fi
    case "$answer" in
      y|yes) return 0 ;;
      n|no) return 1 ;;
      *) echo "Please answer yes or no." ;;
    esac
  done
}

want_choice() {
  choice="$(normalize_choice "$1")"
  prompt="$2"
  default="$3"
  case "$choice" in
    1|true|yes|y|on) return 0 ;;
    0|false|no|n|off) return 1 ;;
    ""|prompt) ask_yes_no "$prompt" "$default" ;;
    *)
      echo "invalid yes/no/prompt choice: $1" >&2
      exit 2
      ;;
  esac
}

install_agentic_loop() {
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
  return 0
fi

if python3 -m pip --version >/dev/null 2>&1; then
  python3 -m pip install --user --upgrade "$PWD"
  echo "agentic-loop installed with pip --user."
  echo "Make sure $BIN_DIR is on PATH."
  python3 -m agentic_loop --version
  return 0
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
}

setup_ollama() {
  if command -v ollama >/dev/null 2>&1; then
    echo "Ollama found: $(command -v ollama)"
  else
    if want_choice "$INSTALL_OLLAMA_CHOICE" "Ollama is not installed. Install it now using the official installer from ollama.com?" "no"; then
      if ! command -v curl >/dev/null 2>&1; then
        echo "curl is required to install Ollama. Install curl, then run:" >&2
        echo "  curl -fsSL https://ollama.com/install.sh | sh" >&2
        return 0
      fi
      echo "Installing Ollama with the official installer..."
      if ! curl -fsSL https://ollama.com/install.sh | sh; then
        echo "Ollama install did not complete. You can retry later:" >&2
        echo "  curl -fsSL https://ollama.com/install.sh | sh" >&2
        return 0
      fi
    else
      echo "Skipping Ollama install."
      echo "Install later with: curl -fsSL https://ollama.com/install.sh | sh"
      return 0
    fi
  fi

  if ! command -v ollama >/dev/null 2>&1; then
    echo "Ollama command is still unavailable; skipping model setup."
    return 0
  fi

  if ollama list 2>/dev/null | awk -v model="$DEFAULT_OLLAMA_MODEL" '$1 == model { found = 1 } END { exit found ? 0 : 1 }'; then
    echo "Ollama model already present: $DEFAULT_OLLAMA_MODEL"
    return 0
  fi

  if want_choice "$PULL_MODEL_CHOICE" "Pull default Ollama model $DEFAULT_OLLAMA_MODEL now?" "yes"; then
    echo "Pulling Ollama model: $DEFAULT_OLLAMA_MODEL"
    if ! ollama pull "$DEFAULT_OLLAMA_MODEL"; then
      echo "Could not pull $DEFAULT_OLLAMA_MODEL. You can retry later:" >&2
      echo "  ollama pull $DEFAULT_OLLAMA_MODEL" >&2
      return 0
    fi
  else
    echo "Skipping model pull."
    echo "Pull later with: ollama pull $DEFAULT_OLLAMA_MODEL"
  fi
}

install_agentic_loop
setup_ollama

echo
echo "Try it:"
echo "  agentic-loop chat"
