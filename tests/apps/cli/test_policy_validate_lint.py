"""#50, X5 — `policy validate FILE` runs the full lint; `policy lint` takes files.

`validate` only parsed and compiled, so a rule that could never fire passed, and
an unknown enum value (`surface: [toolargs]`) was accepted; `lint` read only the
database, so a file could not be linted before it was loaded.
"""

from __future__ import annotations

from typer.testing import CliRunner

from agentfox.apps.cli.main import app
from tests.conftest import as_user

runner = CliRunner()

DEAD = """
key: dead
rules:
  - id: never
    when: {surface: [compleiton]}
    effect: block
"""

TYPO = """
key: typo
rules:
  - id: half
    when: {surface: [input, toolargs]}
    effect: block
"""

GOOD = """
key: good
rules:
  - id: ok
    when: {surface: [input], detection: {entity_prefix: PII}}
    effect: redact
"""


def _file(tmp_path, name, body):
    path = tmp_path / name
    path.write_text(body)
    return str(path)


def test_validate_rejects_an_unreachable_rule(tmp_path):
    result = runner.invoke(app, ["policy", "validate", _file(tmp_path, "d.yaml", DEAD)])
    assert result.exit_code == 1, result.output
    assert "unreachable" in result.output


def test_validate_rejects_an_unknown_enum_value(tmp_path):
    result = runner.invoke(app, ["policy", "validate", _file(tmp_path, "t.yaml", TYPO)])
    assert result.exit_code == 1, result.output
    assert "unknown-value" in result.output


def test_validate_accepts_a_clean_file(tmp_path):
    result = runner.invoke(app, ["policy", "validate", _file(tmp_path, "g.yaml", GOOD)])
    assert result.exit_code == 0, result.output
    assert "valid" in result.output


def test_lint_takes_files(tmp_path):
    bad = runner.invoke(app, ["policy", "lint", _file(tmp_path, "t.yaml", TYPO)])
    assert bad.exit_code == 1 and "LINT FAIL" in bad.output
    good = runner.invoke(app, ["policy", "lint", _file(tmp_path, "g.yaml", GOOD)])
    assert good.exit_code == 0, good.output


def test_the_validate_route_runs_the_lint(client):
    response = client.post(
        "/api/policies/validate", json={"body": TYPO}, headers=as_user("admin@example.com")
    ).json()
    assert response["valid"] is False
    assert "toolargs" in response["error"]
