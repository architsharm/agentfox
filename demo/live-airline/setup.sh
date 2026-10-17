#!/usr/bin/env bash
# Clone OpenAI's airline customer-service demo at a pinned commit, make a venv with its
# requirements plus AgentFox (editable, from this repo), and add the AgentFox hook to
# its main.py. Safe to run again.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
UPSTREAM_URL="https://github.com/openai/openai-cs-agents-demo.git"
UPSTREAM_SHA="bd7bfca0f5abf50529370814c3e7c88542011925"
UPSTREAM="$HERE/upstream"
BACKEND="$UPSTREAM/python-backend"

command -v uv >/dev/null || { echo "uv is required: https://docs.astral.sh/uv/" >&2; exit 1; }

if [ ! -d "$UPSTREAM/.git" ]; then
  git clone --quiet "$UPSTREAM_URL" "$UPSTREAM"
fi
# Discard an earlier hook so the checkout is clean, then pin.
git -C "$UPSTREAM" checkout --quiet -- python-backend/main.py 2>/dev/null || true
git -C "$UPSTREAM" fetch --quiet origin "$UPSTREAM_SHA" 2>/dev/null || true
git -C "$UPSTREAM" checkout --quiet --detach "$UPSTREAM_SHA"
echo "upstream: openai-cs-agents-demo @ $(git -C "$UPSTREAM" rev-parse --short HEAD)"

if [ ! -x "$HERE/.venv/bin/python" ]; then
  uv venv --quiet --python 3.12 "$HERE/.venv"
fi
uv pip install --quiet --python "$HERE/.venv/bin/python" \
  -r "$BACKEND/requirements.txt" -c "$HERE/constraints.txt" -e "$REPO"
echo "venv: $HERE/.venv (agentfox editable from $REPO)"

cp "$HERE/agentfox_wiring.py" "$BACKEND/agentfox_wiring.py"
"$HERE/.venv/bin/python" "$HERE/patch_main.py" "$BACKEND/main.py"
