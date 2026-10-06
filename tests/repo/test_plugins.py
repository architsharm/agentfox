"""The operator plugins (plugins/) must not drift from the product they drive.

Three guarantees, each cheap and offline:
  * every `agentfox …` command/flag, repo path and docs-map entry in the plugin markdown
    is real, and the Claude Code plugin's copies of plugins/shared/ match their originals
    (scripts/check_plugins.py);
  * the safety hook asks before exactly the commands that change what gets blocked, and
    never on look-alikes (plugins/claude-code/scripts/guard_blocking_commands.py);
  * Appendix C's generated route tables match the running app (scripts/api_routes.py).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
HOOK = REPO / "plugins" / "claude-code" / "scripts" / "guard_blocking_commands.py"


def _run(args: list[str], **kwargs) -> subprocess.CompletedProcess:
    env = {**__import__("os").environ, "PYTHONPATH": str(REPO / "src")}
    return subprocess.run(
        args, cwd=REPO, capture_output=True, text=True, env=env, timeout=120, **kwargs
    )


def test_plugin_markdown_matches_the_live_cli_and_repo():
    result = _run([sys.executable, str(REPO / "scripts" / "check_plugins.py")])
    assert result.returncode == 0, result.stdout + result.stderr


def test_appendix_c_routes_are_generated_from_the_app():
    result = _run([sys.executable, str(REPO / "scripts" / "api_routes.py"), "--check"])
    assert result.returncode == 0, result.stdout + result.stderr


def _decision(command: str) -> str:
    result = _run(
        [sys.executable, str(HOOK)], input=json.dumps({"tool_input": {"command": command}})
    )
    assert result.returncode == 0
    if not result.stdout.strip():
        return "allow"
    return json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"]


@pytest.mark.parametrize(
    "command",
    [
        "agentfox policy enforce baseline",
        "uv run --project /r agentfox policy observe baseline",
        "python -m agentfox.apps.cli.main agents kill payments-ops",
        "cd /x && agentfox agents quarantine s -r incident",
        "NOMETRIA_DATABASE_URL=sqlite:////tmp/x.db agentfox demo",
        "plugins/claude-code/scripts/agentfox.sh seed",
        "agentfox db downgrade base",
        "agentfox guardrails apply rule.yaml --mode enforce",
        "agentfox boundary set support --mode=enforce",
        "agentfox auth issue a@b.c",
        "agentfox check . --json --submit",
        "curl -X POST localhost:8080/api/policies/baseline/mode -d '{}'",
        # An automated change is still a change: applying or undoing a proposal moves
        # live enforcement, so it asks like every other blocking command.
        "agentfox proposals apply chp_01h2",
        "agentfox proposals rollback chp_01h2 --actor a@b.c --reason 'made it worse'",
        "curl -X POST localhost:8080/api/proposals/chp_01h2/apply",
        "agentfox proposals verify chp_01h2 --actor a@b.c --note worse --failed",
        # The same commands under their consolidated names.
        "agentfox admin seed",
        "agentfox admin db downgrade base",
        "agentfox policy rules apply rule.yaml --mode enforce",
        "agentfox declare boundary support --mode=enforce",
        "agentfox declare escalation --agent a --mode enforce",
        "agentfox admin auth issue a@b.c",
        "agentfox scan . --json --submit",
        "agentfox scan --sessions --submit",
        "agentfox policy proposals apply chp_01h2",
        "agentfox policy proposals rollback chp_01h2 --actor a@b.c --reason x",
        "agentfox policy proposals verify chp_01h2 --actor a@b.c --note worse --failed",
        # Grants are containment: a grant is what lets a refused tool call through.
        "agentfox permit grant payments-ops payments.transfer --limit amount=500",
        "agentfox permit revoke cap_01h2",
        "agentfox capability grant payments-ops payments.transfer",
        "uv run agentfox capability revoke cap_01h2",
        "agentfox permit user alice 'crm:*'",
        "agentfox admin users create ops@example.com --role owner",
        "curl -X POST localhost:8080/api/identities/idn_1/capabilities -d '{}'",
        # Deciding an approval lets a held call run.
        "agentfox permit approvals approve apr_01h2",
        "agentfox approvals deny apr_01h2 -r no",
    ],
)
def test_blocking_commands_require_confirmation(command):
    assert _decision(command) == "ask"


@pytest.mark.parametrize(
    "command",
    [
        "agentfox findings --json",
        "agentfox policy list",
        "agentfox policy simulate -f p.yaml",
        "agentfox proposals list --status proposed",
        "agentfox proposals show chp_01h2",
        "agentfox proposals verify chp_01h2 --actor a@b.c --note held",
        "agentfox check . --fail",
        "agentfox escalation set --agent a --mode observe",
        "agentfox scan . --fail",
        "agentfox declare escalation --agent a --mode observe",
        "agentfox policy proposals list",
        "agentfox permit approvals list",
        "agentfox report",
        "agentfox permit list",
        "agentfox admin users list",
        "agentfox demo-notes.md",
        "git commit -m 'agentfox policy enforce baseline'",
        "echo agentfox seed",
        "cat docs/agentfox-policy-enforce.md",
    ],
)
def test_read_only_and_look_alike_commands_pass_silently(command):
    assert _decision(command) == "allow"


def test_hook_never_breaks_on_garbage_input():
    result = _run([sys.executable, str(HOOK)], input="not json")
    assert result.returncode == 0 and result.stdout == ""
