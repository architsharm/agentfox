#!/usr/bin/env bash
# AgentFox Quickscan — one command, no account, nothing leaves this machine.
#
#   curl -fsSL https://raw.githubusercontent.com/architsharm/agentfox/main/scripts/quickscan.sh | bash
#
# Installs AgentFox into a throwaway virtualenv (removed on exit either way) and runs
# `agentfox scan --sessions` against the current directory, which also reads the MCP
# servers and skills your AI tools load at user level (`agentfox scan machine`). It installs from git rather than
# PyPI so a first look always runs the current main, not the last release — this script
# exists only to skip "create a venv, activate it, pip install" for that first look. No step here talks to
# anything but PyPI/GitHub (to fetch the package itself) and your local filesystem.

set -euo pipefail

REPO_URL="https://github.com/architsharm/agentfox.git"
TARGET_DIR="${1:-.}"

info() { printf '%s\n' "$*" >&2; }

PYTHON_BIN="${AGENTFOX_PYTHON:-}"
# AgentFox needs Python 3.11+ (pyproject's requires-python). Take the first interpreter
# on PATH that is new enough, rather than failing deep inside pip on an old python3.
if [ -z "$PYTHON_BIN" ]; then
  for candidate in python3.13 python3.12 python3.11 python3 python; do
    if command -v "$candidate" >/dev/null 2>&1 &&
      "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then
      PYTHON_BIN="$candidate"
      break
    fi
  done
fi
if [ -z "$PYTHON_BIN" ]; then
  info "AgentFox Quickscan needs Python 3.11+ and none was found on PATH."
  info "Install Python 3.11 or newer (or set AGENTFOX_PYTHON), then re-run this script."
  exit 1
fi

WORKDIR="$(mktemp -d -t agentfox-quickscan-XXXXXX)"
cleanup() { rm -rf "$WORKDIR"; }
trap cleanup EXIT

info "AgentFox Quickscan — setting up in a throwaway environment (nothing leaves this machine)..."

"$PYTHON_BIN" -m venv "$WORKDIR/venv"
# shellcheck disable=SC1091
source "$WORKDIR/venv/bin/activate"

if ! pip install --quiet --disable-pip-version-check "git+${REPO_URL}" >"$WORKDIR/install.log" 2>&1; then
  info "Install failed. Last few lines:"
  tail -n 20 "$WORKDIR/install.log" >&2
  info ""
  info "You can also install it yourself: pip install \"git+${REPO_URL}\""
  exit 1
fi

# Not `exec`: that would replace this shell, and the EXIT trap that removes the
# throwaway environment would never run. The scan's exit code is passed through.
status=0
agentfox scan --sessions "$TARGET_DIR" || status=$?
exit "$status"
