#!/usr/bin/env bash
# Run the agentfox CLI, so skills never have to guess how it is installed here.
#
# Published path: a pinned install from this repository at one exact commit.
# The Claude Directory does not accept a PyPI version as a pin, because the owner of a
# published release can add files to it afterwards and uv, pipx and pip each install
# whichever file best fits the machine. The commit below is the only code that runs.
# Bump it with the release tag; it must stay a literal 40-character SHA on one line,
# because the directory's check does not follow shell substitutions.
#
# Working on AgentFox itself? Set AGENTFOX_LOCAL=1 and this runs your working tree:
#   1. an installed `agentfox` on PATH
#   2. a source checkout with uv    -> `uv run --project <root> agentfox`
#   3. a source checkout with .venv -> .venv/bin/python -m agentfox.apps.cli.main
set -euo pipefail

if [[ "${AGENTFOX_LOCAL:-}" == "1" ]]; then
  if command -v agentfox >/dev/null 2>&1; then
    exec agentfox "$@"
  fi
  root="$(git rev-parse --show-toplevel 2>/dev/null || true)"
  if [[ -n "$root" && -f "$root/pyproject.toml" ]] && grep -q '^name = "agentfox"' "$root/pyproject.toml"; then
    if command -v uv >/dev/null 2>&1; then
      exec uv run --project "$root" agentfox "$@"
    fi
    if [[ -x "$root/.venv/bin/python" ]]; then
      PYTHONPATH="$root/src${PYTHONPATH:+:$PYTHONPATH}" exec "$root/.venv/bin/python" -m agentfox.apps.cli.main "$@"
    fi
  fi
  echo "AGENTFOX_LOCAL=1 is set, but no agentfox checkout was found from here." >&2
  echo "Unset it to run the pinned release instead." >&2
  exit 127
fi

if ! command -v uvx >/dev/null 2>&1; then
  echo "agentfox needs uv to run. Install uv from https://docs.astral.sh/uv/ and try again." >&2
  exit 127
fi

exec uvx --from "git+https://github.com/architsharm/agentfox@42cd5bffdaede4e049a18abfb796cc653751672e" agentfox "$@"
