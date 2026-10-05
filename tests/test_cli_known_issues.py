"""Regressions for known CLI defects — one test (or small group) per fix.

Each test names the behaviour that was wrong, so a future failure reads as "this came
back", not as an unexplained assertion.
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

import pytest
from typer.testing import CliRunner

from agentfox.cli.main import app

runner = CliRunner()
REPO = Path(__file__).resolve().parents[1]

REFUND_POLICY = (
    "Refunds under $10 are auto-approved. Refunds between $10 and $100 must run a "
    "fraud check before proceeding, and refunds over $100 require approval from the "
    "finance team.\n"
)


def flat(output: str) -> str:
    return " ".join(output.split())


def _json(output: str):
    """Parse JSON output, ignoring Alembic's stamp log lines on a first-run database."""
    lines = [line for line in output.splitlines() if not line.startswith("INFO")]
    return json.loads("\n".join(lines))


def _seed() -> dict:
    from agentfox.db import session_scope
    from agentfox.seed import seed

    with session_scope() as session:
        return seed(session)


def _policy_mode(key: str) -> str | None:
    from agentfox.cli.demo import _current_mode

    return _current_mode(key)


# ---------------------------------------------------------------------------
# 1. init tells the truth about each pack, and writes the real defaults
# ---------------------------------------------------------------------------


def test_init_reports_each_pack_in_its_declared_mode(tmp_path):
    result = runner.invoke(app, ["init", "--path", str(tmp_path)])
    assert result.exit_code == 0, result.output
    output = flat(result.output)
    assert "baseline observe" in output
    assert "tool-containment enforce" in output
    assert "nothing is blocked yet" not in output


def test_init_config_template_matches_the_settings_defaults(tmp_path):
    from agentfox.config import Settings

    runner.invoke(app, ["init", "--path", str(tmp_path), "--env", "staging"])
    table = tomllib.loads((tmp_path / "agentfox.toml").read_text())["agentfox"]
    assert table["environment"] == "staging"
    for key, value in table.items():
        assert key in Settings.model_fields, f"{key} is not a Settings field"
        if key != "environment":
            assert value == Settings.model_fields[key].default, key


# ---------------------------------------------------------------------------
# 2. the demo's enforce promotion is temporary
# ---------------------------------------------------------------------------


def test_demo_restores_the_promoted_policy_when_a_step_fails(monkeypatch):
    from agentfox.cli import demo

    _seed()
    assert _policy_mode("baseline") == "observe"

    def promote_then_fail():
        with demo.session_scope() as session:
            demo.set_mode(session, "baseline", "enforce")
        raise RuntimeError("a demo step failed")

    monkeypatch.setattr(demo, "_walkthrough", promote_then_fail)
    with pytest.raises(RuntimeError):
        demo.run()
    assert _policy_mode("baseline") == "observe"


def test_demo_command_restores_the_policy_and_says_so(monkeypatch):
    from agentfox.cli import demo

    _seed()

    def promote():
        with demo.session_scope() as session:
            demo.set_mode(session, "baseline", "enforce")
        return {}

    monkeypatch.setattr(demo, "_walkthrough", promote)
    result = runner.invoke(app, ["demo"])
    assert result.exit_code == 0, result.output
    assert "baseline policy restored to observe" in flat(result.output)
    assert _policy_mode("baseline") == "observe"


# ---------------------------------------------------------------------------
# 3. seed masks agent keys unless asked
# ---------------------------------------------------------------------------


def test_seed_masks_agent_keys_by_default():
    result = runner.invoke(app, ["seed"])
    assert result.exit_code == 0, result.output
    assert re.search(r"nom_agt_\w{4}…", result.output)
    assert not re.search(r"nom_agt_\w{5,}", result.output)
    assert "--show-keys" in flat(result.output)


def test_seed_show_keys_prints_them_in_full():
    result = runner.invoke(app, ["seed", "--show-keys"])
    assert result.exit_code == 0, result.output
    assert re.search(r"nom_agt_\w{20,}", result.output)


# ---------------------------------------------------------------------------
# 4. DB-backed groups initialise the schema instead of dying on "no such table"
# ---------------------------------------------------------------------------


@pytest.fixture
def tableless_db(tmp_path, monkeypatch):
    from sqlalchemy import inspect

    from agentfox import db
    from agentfox.config import reset_settings_cache

    monkeypatch.setenv("NOMETRIA_DATABASE_URL", f"sqlite:///{tmp_path / 'fresh.db'}")
    reset_settings_cache()
    db.reset_engine()
    assert not inspect(db.get_engine()).has_table("agents")
    yield
    db.reset_engine()
    reset_settings_cache()


def test_findings_json_on_a_fresh_database(tableless_db):
    result = runner.invoke(app, ["findings", "--json"])
    assert result.exit_code == 0, result.output
    assert _json(result.output) == []


@pytest.mark.parametrize(
    ("args", "exit_code"),
    [
        (["auth", "tokens", "--json"], 0),
        (["sources", "list", "--json"], 0),
        (["escalation", "scan"], 0),
        (["entitlement", "report"], 0),
        (["boundary", "check", "nobody", "what is our refund policy?"], 1),
        (["guardrails", "show"], 0),
        (["guardrails", "check", "--json"], 0),
    ],
)
def test_db_backed_groups_work_on_a_fresh_database(tableless_db, args, exit_code):
    result = runner.invoke(app, args)
    assert result.exception is None or isinstance(result.exception, SystemExit), repr(
        result.exception
    )
    assert "no such table" not in result.output
    assert result.exit_code == exit_code, result.output


# ---------------------------------------------------------------------------
# 5. doctor --json fails the build on a bad check
# ---------------------------------------------------------------------------


def test_doctor_json_exits_nonzero_on_a_bad_check(monkeypatch):
    monkeypatch.setattr("agentfox.guardrails.available_detectors", lambda: {})
    result = runner.invoke(app, ["doctor", "--json"])
    assert result.exit_code == 1, result.output
    checks = _json(result.output)
    assert any(c["check"] == "detectors" and c["state"] == "bad" for c in checks)


def test_doctor_json_exits_zero_when_nothing_is_bad():
    result = runner.invoke(app, ["doctor", "--json"])
    assert result.exit_code == 0, result.output
    assert not any(c["state"] == "bad" for c in _json(result.output))


# ---------------------------------------------------------------------------
# 6. scan mcp never silently scans the seed fixture
# ---------------------------------------------------------------------------


def test_scan_mcp_without_a_file_never_scans_the_seed_fixture():
    """Without --file there is no tool list, and the output says so instead of
    quietly scanning the demo fixture's tools as if the server had declared them."""
    _seed()
    result = runner.invoke(app, ["scan", "mcp", "internal-tools"])
    assert result.exit_code == 0, result.output
    output = flat(result.output)
    assert "tools: not listed" in output
    assert "--file tools.json" in output
    assert "digest" not in output


def test_scan_mcp_seed_fixture_must_be_asked_for():
    _seed()
    result = runner.invoke(app, ["scan", "mcp", "internal-tools", "--seed-fixture"])
    assert result.exit_code == 0, result.output
    assert "internal-tools" in result.output


def test_scan_mcp_scans_the_given_file(tmp_path):
    from agentfox.seed import MCP_TOOLS

    _seed()
    path = tmp_path / "tools.json"
    path.write_text(json.dumps(MCP_TOOLS[:1]))
    result = runner.invoke(app, ["scan", "mcp", "internal-tools", "--file", str(path)])
    assert result.exit_code == 0, result.output
    assert "1 tools" in flat(result.output)


# ---------------------------------------------------------------------------
# 7. guardrails compile --apply actually saves
# ---------------------------------------------------------------------------


def test_guardrails_compile_apply_saves_the_ladder(tmp_path):
    from agentfox.business import all_ladders
    from agentfox.db import session_scope

    path = tmp_path / "refunds.txt"
    path.write_text(REFUND_POLICY)
    result = runner.invoke(app, ["guardrails", "compile", str(path), "--apply"])
    assert result.exit_code == 0, (result.output, result.exception)
    output = flat(result.output)
    assert "Saved 1 ladder(s)" in output
    assert "--mode enforce" in output
    assert "apply --enforce" not in output

    with session_scope() as session:
        ladders = {lad.key: lad for lad in all_ladders(session)}
    assert "refunds-payments-refund" in ladders
    assert ladders["refunds-payments-refund"].mode == "observe"


# ---------------------------------------------------------------------------
# 8. entitlement report points at a command that exists
# ---------------------------------------------------------------------------


def test_entitlement_report_hint_names_a_real_command():
    result = runner.invoke(app, ["entitlement", "report"])
    output = flat(result.output)
    assert "agentfox declare principal" in output
    assert "principal set" not in output
    assert runner.invoke(app, ["declare", "principal", "--help"]).exit_code == 0


# ---------------------------------------------------------------------------
# 9. compliance status --framework --verbose filters the table
# ---------------------------------------------------------------------------


def test_compliance_status_verbose_honours_the_framework():
    from agentfox.compliance import controls_for_framework, latest_statuses
    from agentfox.compliance.catalog import load_catalog
    from agentfox.db import session_scope

    _seed()
    assert runner.invoke(app, ["compliance", "compute"]).exit_code == 0

    with session_scope() as session:
        computed = set(latest_statuses(session))
        for framework in load_catalog()["frameworks"]:
            mapped = {c["key"] for c in controls_for_framework(session, framework)}
            inside, outside = computed & mapped, computed - mapped
            if inside and outside:
                break
        else:  # pragma: no cover - catalog shape guard
            pytest.skip("no framework maps a strict subset of controls")

    result = runner.invoke(app, ["compliance", "status", "--framework", framework, "--verbose"])
    assert result.exit_code == 0, result.output
    for key in inside:
        assert key in result.output
    for key in outside:
        assert key not in result.output


# ---------------------------------------------------------------------------
# 10. policy effective resolves for the configured environment
# ---------------------------------------------------------------------------


def test_policy_effective_defaults_to_the_configured_environment(monkeypatch):
    from agentfox.config import reset_settings_cache

    _seed()
    default = runner.invoke(app, ["policy", "effective"])
    assert default.exit_code == 0, default.output
    assert "effective policy in development" in flat(default.output)

    monkeypatch.setenv("NOMETRIA_ENVIRONMENT", "staging")
    reset_settings_cache()
    configured = runner.invoke(app, ["policy", "effective"])
    assert "effective policy in staging" in flat(configured.output)

    explicit = runner.invoke(app, ["policy", "effective", "--environment", "production"])
    assert "effective policy in production" in flat(explicit.output)


# ---------------------------------------------------------------------------
# 11. the console script goes through main(), which maps Ctrl-C to 130
# ---------------------------------------------------------------------------


def test_console_script_points_at_main():
    project = tomllib.loads((REPO / "pyproject.toml").read_text())
    assert project["project"]["scripts"]["agentfox"] == "agentfox.cli.main:main"


def test_main_maps_keyboard_interrupt_to_130(monkeypatch):
    import importlib

    # `agentfox.cli` re-exports the `main` function, so import the module by path.
    cli_main = importlib.import_module("agentfox.cli.main")

    def interrupted():
        raise KeyboardInterrupt

    monkeypatch.setattr(cli_main, "app", interrupted)
    with pytest.raises(SystemExit) as exit_info:
        cli_main.main()
    assert exit_info.value.code == 130


# ---------------------------------------------------------------------------
# 12. compliance validate
# ---------------------------------------------------------------------------


def test_compliance_validate_passes_on_the_shipped_catalog():
    result = runner.invoke(app, ["compliance", "validate"])
    assert result.exit_code == 0, result.output
    output = flat(result.output)
    assert "catalog valid" in output
    assert "draft" in output and "reviewed" in output


BROKEN_CATALOG = """
version: test
frameworks:
  soc2: SOC 2
controls:
  - key: C-1
    title: one
    objective: o
    family: C
    status_rule: {kind: presence}
    mappings: {soc2: ["CC1"]}
  - key: C-1
    title: duplicate
    objective: o
    family: C
    status_rule: {kind: vibes}
    mappings: {made-up: ["X"]}
  - key: C-2
    title: no objective
    family: C
    status_rule: {kind: ratio}
"""

BROKEN_OBLIGATIONS = """
obligations:
  - framework: nowhere
    reference: Art. 1
"""


@pytest.fixture
def compliance_dir(tmp_path, monkeypatch):
    from agentfox.config import reset_settings_cache

    monkeypatch.setenv("NOMETRIA_COMPLIANCE_DIR", str(tmp_path))
    reset_settings_cache()
    return tmp_path


def test_compliance_validate_reports_every_problem(compliance_dir):
    (compliance_dir / "controls.yaml").write_text(BROKEN_CATALOG)
    (compliance_dir / "obligations.yaml").write_text(BROKEN_OBLIGATIONS)
    result = runner.invoke(app, ["compliance", "validate"])
    assert result.exit_code == 1, result.output
    output = flat(result.output)
    assert "C-1: duplicate control key" in output
    assert "'vibes'" in output
    assert "undeclared framework 'made-up'" in output
    assert "C-2: missing objective" in output
    assert "undeclared framework 'nowhere'" in output
    assert "catalog valid" not in output


def test_compliance_validate_reports_unparseable_yaml(compliance_dir):
    (compliance_dir / "controls.yaml").write_text("controls: [unclosed\n")
    (compliance_dir / "obligations.yaml").write_text("obligations: []\n")
    result = runner.invoke(app, ["compliance", "validate"])
    assert result.exit_code == 1
    assert "does not parse" in flat(result.output)
