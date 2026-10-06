"""`agentfox policy packs` and `agentfox findings --types`."""

from __future__ import annotations

import json

from typer.testing import CliRunner

from agentfox.apps.cli.main import app

runner = CliRunner()


def flat(output: str) -> str:
    return " ".join(output.split())


def test_bare_policy_packs_is_still_the_policy_file_table():
    bare = runner.invoke(app, ["policy", "packs"])
    files = runner.invoke(app, ["policy", "packs", "files"])
    assert bare.exit_code == 0, bare.output
    assert bare.output == files.output
    assert "tool-containment" in bare.output and "shipped" in bare.output


def test_list_shows_every_builtin_pack():
    result = runner.invoke(app, ["policy", "packs", "list", "--json"])
    assert result.exit_code == 0, result.output
    rows = {row["id"]: row for row in json.loads(result.output)}
    assert {"baseline", "eu-ai-act", "payments/refunds", "compliance/catalog"} <= set(rows)
    assert rows["payments/refunds"]["contents"]["ladders"] == ["refund-approval.yaml"]


def test_show_names_what_a_pack_ships():
    result = runner.invoke(app, ["policy", "packs", "show", "eu-ai-act"])
    assert result.exit_code == 0, result.output
    output = flat(result.output)
    assert "eu-ai-act 1.0.0 stable" in output
    assert "fallback protects unconfigured deployments at tier(s) high, prohibited" in output


def test_show_an_unknown_pack_is_a_message():
    result = runner.invoke(app, ["policy", "packs", "show", "nope/nothing"])
    assert result.exit_code == 2
    assert "no pack 'nope/nothing'" in flat(result.output)


def test_test_runs_the_cases():
    result = runner.invoke(app, ["policy", "packs", "test", "payments/refunds"])
    assert result.exit_code == 0, result.output
    assert "7/7 case(s) passed" in flat(result.output)


def test_validate_fails_on_a_broken_pack(tmp_path):
    (tmp_path / "pack.yaml").write_text(
        "id: broken\nversion: 0.1.0\nmaturity: stable\nowners: [me]\n"
    )
    result = runner.invoke(app, ["policy", "packs", "validate", str(tmp_path)])
    assert result.exit_code == 1
    assert "a stable pack needs a README.md" in flat(result.output)


def test_validate_prints_the_schema():
    result = runner.invoke(app, ["policy", "packs", "validate", "--schema"])
    assert result.exit_code == 0
    assert json.loads(result.output)["title"] == "PackManifest"


def test_findings_types_lists_the_registry():
    result = runner.invoke(app, ["findings", "--types", "--json"])
    assert result.exit_code == 0, result.output
    rows = {row["type"]: row for row in json.loads(result.output)}
    assert rows["containment"]["owner"] == "containment"
