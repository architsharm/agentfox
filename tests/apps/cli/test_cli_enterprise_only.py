"""Enterprise-only commands on the open-core wheel say what they are.

The CLI reference lists `report review-packet`, `report status`, `admin catalog sync`
and `scan monitors`. Without AgentFox Enterprise they used to fall through to the
group's default command and fail with "Got unexpected extra argument (review-packet)"
or "No such option '--framework'". Each one now prints the same "part of AgentFox
Enterprise, which is not installed here" message `report evidence` does, and exits 2.

The tree is built at import time, so the open-core run is a subprocess with
extensions disabled.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]

COMMANDS = [
    ["report", "review-packet"],
    ["report", "status", "--framework", "eu-ai-act"],
    ["report", "risk"],
    ["report", "obligations"],
    ["report", "frameworks"],
    ["report", "board"],
    ["report", "signoff"],
    ["report", "evidence", "--agent", "x"],
    ["admin", "catalog", "sync"],
    ["scan", "monitors", "list"],
    ["scan", "monitors", "add", "github_repo", "acme/bot"],
]

SCRIPT = """
import json, sys
sys.modules["agentfox_ee"] = None
from typer.testing import CliRunner
from agentfox.apps.cli.main import app
runner = CliRunner()
out = []
for argv in json.loads(sys.argv[1]):
    r = runner.invoke(app, argv)
    out.append({"argv": argv, "code": r.exit_code, "output": r.output})
print(json.dumps(out))
"""


def _run_open_core(commands: list[list[str]], tmp_path: Path) -> list[dict]:
    env = {
        **os.environ,
        "AGENTFOX_DISABLE_EXTENSIONS": "1",
        "AGENTFOX_STATE_DIR": str(tmp_path),
        "HOME": str(tmp_path),
        "PYTHONPATH": str(REPO / "src"),
        "COLUMNS": "200",
    }
    proc = subprocess.run(
        [sys.executable, "-c", SCRIPT, json.dumps(commands)],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
    )
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_enterprise_commands_say_so_on_the_open_core(tmp_path):
    for result in _run_open_core(COMMANDS, tmp_path):
        argv, output = " ".join(result["argv"]), result["output"]
        assert result["code"] == 2, (argv, output)
        assert "part of AgentFox Enterprise, which is not installed here" in output, (argv, output)
        assert "unexpected extra argument" not in output, (argv, output)
        assert "No such option" not in output, (argv, output)


def test_the_reference_badges_enterprise_commands():
    cli = json.loads((REPO / "dashboard/lib/generated/reference/cli.json").read_text())
    nodes: dict[str, dict] = {}

    def walk(node: dict) -> None:
        nodes[node["path"]] = node
        for child in node["commands"]:
            walk(child)

    walk(cli["root"])
    for path in (
        "report review-packet",
        "report status",
        "report evidence",
        "admin catalog",
        "admin catalog sync",
        "scan monitors",
        "scan monitors add",
    ):
        assert nodes[path]["enterprise"] is True, path
    for path in ("report", "report summary", "report verify", "scan", "scan repo", "admin"):
        assert nodes[path]["enterprise"] is False, path
