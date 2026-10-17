#!/usr/bin/env bash
# Run the agentfox CLI however it is available here, so skills never have to guess.
#   1. an installed `agentfox` on PATH (or the older `agentfox` alias)
#   2. a source checkout of this repo with uv  -> `uv run agentfox`
#   3. a source checkout with a local .venv    -> .venv/bin/python -m agentfox.apps.cli.main
# Otherwise print the install line and exit 127.
set -euo pipefail
for bin in agentfox agentfox; do
  if command -v "$bin" >/dev/null 2>&1; then
    exec "$bin" "$@"
  fi
done
root="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [[ -n "$root" && -f "$root/pyproject.toml" ]] && grep -q '^name = "agentfox"' "$root/pyproject.toml"; then
  if command -v uv >/dev/null 2>&1; then
    exec uv run --project "$root" agentfox "$@"
  fi
  if [[ -x "$root/.venv/bin/python" ]]; then
    PYTHONPATH="$root/src${PYTHONPATH:+:$PYTHONPATH}" exec "$root/.venv/bin/python" -m agentfox.apps.cli.main "$@"
  fi
fi
echo "agentfox is not installed. Install it with:" >&2
echo '  pip install "git+https://github.com/architsharm/agentfox.git"' >&2
exit 127
