#!/usr/bin/env bash
# Build the two scratch environments the head-to-head needs, outside the project venv.
#
#   bash benchmarks/head_to_head/setup_venvs.sh [DIR]   # default DIR: $TMPDIR/h2h-venvs
#
# 1. agentdojo==0.1.35, only to regenerate the traces (a copy is committed in results/).
# 2. llm-guard (pins transformers==4.51.3, which conflicts with the project's own pins). The same
#    venv scores Prompt Guard 2; that model is gated, see the README before running it.
#
# Model weights download into the normal Hugging Face cache (~/.cache/huggingface).
set -euo pipefail
DIR="${1:-${TMPDIR:-/tmp}/h2h-venvs}"
uv venv -q --python 3.11 "$DIR/agentdojo"
uv pip install -q --python "$DIR/agentdojo/bin/python" agentdojo==0.1.35
uv venv -q --python 3.11 "$DIR/scanners"
uv pip install -q --python "$DIR/scanners/bin/python" llm-guard==0.3.16
echo "export H2H_SCANNER_PYTHON=$(cd "$DIR" && pwd)/scanners/bin/python"
echo "export H2H_AGENTDOJO_PYTHON=$(cd "$DIR" && pwd)/agentdojo/bin/python"
