#!/usr/bin/env bash
# Run the released agentfox CLI, so skills never have to guess how it is installed here.
#
# One invocation, on purpose. This installs from this repository at one exact commit, and
# does nothing else.
#
# Two reasons it is not cleverer than that. A PyPI version is not a pin: the owner of a
# published release can add files to it afterwards, and uv, pipx and pip each install
# whichever file best fits the machine. And a launcher that *might* run your working tree,
# *might* run whatever `agentfox` is on PATH and *might* run a release is a launcher nobody
# can read, including the Claude Directory's scanner, which refuses what it cannot confirm.
#
# Bump the commit with each release. It must stay a literal 40-character SHA on one line:
# a shell substitution here stops the pin being checkable, which defeats the point.
#
# Working on AgentFox itself? Don't use this script. From a checkout, run `uv run agentfox`,
# which is what plugins/shared/AGENTS.md tells you to use and what runs your working tree.
set -euo pipefail

if ! command -v uvx >/dev/null 2>&1; then
  echo "agentfox needs uv to run. Install uv from https://docs.astral.sh/uv/ and try again." >&2
  exit 127
fi

exec uvx --from "git+https://github.com/architsharm/agentfox@7a0b23fdfd9224c05d84c4fd66df405478976a7f" agentfox "$@"
