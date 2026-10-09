"""`agentfox policy import FILE` — plan by default, `--apply` saves in observe."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from agentfox.apps.cli.main import app

runner = CliRunner()
CORPUS = Path(__file__).resolve().parents[2] / "corpus" / "agent_governance" / "policies"

RULES = """
apiVersion: governance.toolkit/v1
name: cli-demo
default_action: allow
rules:
  - name: no-shell
    condition: "tool_name == 'run_shell'"
    action: deny
  - name: owner-only
    condition: "user.id == resource.owner"
    action: deny
"""


def _file(tmp_path: Path, body: str) -> str:
    path = tmp_path / "policy.yaml"
    path.write_text(body)
    return str(path)


def _policy(key: str):
    from agentfox.core.db import session_scope
    from agentfox.core.models import Policy
    from agentfox.platform.policy import current_binding

    with session_scope() as session:
        policy = session.query(Policy).filter_by(key=key).one_or_none()
        if policy is None:
            return None
        return current_binding(session, policy.id)[0].mode


def test_import_is_listed_under_policy():
    assert "import" in runner.invoke(app, ["policy", "--help"]).output


def test_plan_lists_every_rule_and_saves_nothing(tmp_path):
    result = runner.invoke(app, ["policy", "import", _file(tmp_path, RULES)])
    assert result.exit_code == 0, result.output
    assert "Unmatched calls pass" in result.output
    assert "not translated" in result.output
    assert "1 translated" in result.output
    assert _policy("imported-cli-demo") is None


def test_json_plan(tmp_path):
    result = runner.invoke(app, ["policy", "import", _file(tmp_path, RULES), "--json"])
    assert result.exit_code == 0, result.output
    plan = json.loads(result.output)
    assert plan["summary"]["untranslatable"] == 1
    assert plan["unmatched_pass"] is True


def test_apply_saves_in_observe(tmp_path):
    result = runner.invoke(app, ["policy", "import", _file(tmp_path, RULES), "--apply", "--yes"])
    assert result.exit_code == 0, result.output
    assert "saved" in result.output
    assert _policy("imported-cli-demo") == "observe"


def test_manifest_reads_its_bundle_from_disk():
    path = CORPUS / "production" / "minimal.yaml"
    result = runner.invoke(app, ["policy", "import", str(path), "--json"])
    assert result.exit_code == 0, result.output
    plan = json.loads(result.output)
    assert plan["format"] == "manifest"
    assert plan["summary"]["translated"] >= 1


def test_unreadable_and_invalid_files_exit_1(tmp_path):
    missing = runner.invoke(app, ["policy", "import", str(tmp_path / "nope.yaml")])
    assert missing.exit_code == 1
    bad = "agent_control_specification_version: 0.4.0-alpha.1\nsurprise: 1\n"
    invalid = runner.invoke(app, ["policy", "import", _file(tmp_path, bad)])
    assert invalid.exit_code == 1
    assert "schema" in invalid.output
