"""`agentfox policy export` and `policy apply`: the workspace file from the terminal."""

from __future__ import annotations

import yaml
from typer.testing import CliRunner

from agentfox.apps.cli.main import app

runner = CliRunner()


def _seed() -> None:
    from agentfox.core.db import session_scope
    from agentfox.fixtures.seed import seed

    with session_scope() as s:
        seed(s)


def test_export_then_apply_a_change(tmp_path):
    _seed()
    out = tmp_path / "agentfox.yaml"
    result = runner.invoke(app, ["policy", "export", "--out", str(out)])
    assert result.exit_code == 0, result.output

    data = yaml.safe_load(out.read_text())
    assert (
        runner.invoke(app, ["policy", "apply", str(out), "--yes"])
        .output.strip()
        .endswith("Nothing to change.")
    )

    data["custom_rules"] = [
        {"key": "rivals", "name": "Rivals", "kind": "terms", "entries": ["Globex"]}
    ]
    out.write_text(yaml.safe_dump(data))
    result = runner.invoke(app, ["policy", "apply", str(out), "--yes"])
    assert result.exit_code == 0, result.output
    assert "rivals" in result.output and "Applied 1 change" in result.output


def test_apply_refuses_a_file_that_is_not_a_workspace(tmp_path):
    bad = tmp_path / "x.yaml"
    bad.write_text("policies: []\n")
    result = runner.invoke(app, ["policy", "apply", str(bad), "--yes"])
    assert result.exit_code == 1 and "workspace file" in result.output
