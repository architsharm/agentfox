"""Fetches ground-truth tool calls from `agentdojo`'s four `v1` suites (banking,
travel, slack, workspace) via `agentdojo_bridge.py`, run in an isolated venv (see
that file's docstring — same pattern as `../agent_security/llm_guard_client.py`),
and writes them to `data/agentdojo_calls.json`.

    uv venv /tmp/agentdojo_venv
    uv pip install --python /tmp/agentdojo_venv/bin/python agentdojo
    AGENTDOJO_VENV_PYTHON=/tmp/agentdojo_venv/bin/python uv run python -m benchmarks.action_safety.fetch_agentdojo

No live LLM call anywhere in this pipeline — `ground_truth()` is a static method on
each task class that returns the `FunctionCall`(s) a *successful* attack (for
injection tasks) or a *correct* agent (for user tasks) would issue, hand-authored by
AgentDojo's own maintainers as the benchmark's answer key. This script extracts that
answer key; it does not simulate an agent choosing to call it.

Two categories, deliberately not "attack"/"benign" in the sense the other F3
datasets use:

  - injection: what a successfully-compromised agent would call, per the task's own
    ground truth (e.g. `send_money` to an attacker-controlled IBAN). These are
    real-shaped tool-call arguments (IBANs, dates, amounts, file paths, Slack
    channel names) — not SQL, not shell commands, not obviously malicious by their
    syntax. See README.md for why that's the actual point of running this dataset,
    not a shortcoming of it.
  - user: what a correctly-behaving agent calls for its legitimate assignment —
    the negative/precision-check set, at real scale (552 calls) and real diversity
    (4 unrelated tool domains) rather than a handful of examples.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
_BRIDGE = Path(__file__).parent / "agentdojo_bridge.py"


def main() -> None:
    python = os.environ.get("AGENTDOJO_VENV_PYTHON")
    if not python or not Path(python).exists():
        raise SystemExit(
            "Set AGENTDOJO_VENV_PYTHON to an interpreter with agentdojo installed "
            "(see agentdojo_bridge.py's docstring)."
        )

    proc = subprocess.run(
        [python, str(_BRIDGE)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if proc.returncode != 0:
        raise SystemExit(f"agentdojo bridge failed:\n{proc.stderr[-4000:]}")

    data = json.loads(proc.stdout)
    print(f"injection calls: {len(data['injection'])}")
    print(f"user calls: {len(data['user'])}")

    by_suite: dict[str, dict[str, int]] = {}
    for kind in ("injection", "user"):
        for row in data[kind]:
            by_suite.setdefault(row["suite"], {"injection": 0, "user": 0})
            by_suite[row["suite"]][kind] += 1
    for suite, counts in sorted(by_suite.items()):
        print(f"  {suite}: injection={counts['injection']} user={counts['user']}")

    DATA_DIR.mkdir(exist_ok=True, parents=True)
    (DATA_DIR / "agentdojo_calls.json").write_text(json.dumps(data, indent=2))
    print("\nwrote data/agentdojo_calls.json")


if __name__ == "__main__":
    main()
