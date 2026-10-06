"""Regressions for CLI output and error paths (#31/#56, #32/#85c, #6, #60, #87).

- `doctor` listed available detectors, hiding enabled ones that cannot run, and a
  dict-vs-set comparison hid the offline-only providers message;
- `test action` without sqlglot lost "[sql]" to Rich markup and called an
  unanalysed statement "reversible";
- `policy rules apply --agent unknown`, `init --path <missing>` and an SQL_ASCII
  Postgres database each ended in a traceback;
- there was no CLI to register an agent or set its budget.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import select
from typer.testing import CliRunner

from agentfox.cli.main import app

runner = CliRunner()


def flat(output: str) -> str:
    return " ".join(output.split())


def _seed() -> None:
    from agentfox.core.db import session_scope
    from agentfox.fixtures.seed import seed

    with session_scope() as session:
        seed(session)


# --- doctor -----------------------------------------------------------------


def _doctor(monkeypatch, enabled: list[str] | None = None) -> dict[str, dict]:
    from agentfox.core.config import reset_settings_cache

    if enabled is not None:
        monkeypatch.setenv("AGENTFOX_ENABLED_DETECTORS", json.dumps(enabled))
    reset_settings_cache()
    result = runner.invoke(app, ["doctor", "--json"])
    lines = [line for line in result.output.splitlines() if not line.startswith("INFO")]
    return {row["check"]: row for row in json.loads("\n".join(lines))}


def test_doctor_names_enabled_detectors_that_cannot_run(monkeypatch):
    checks = _doctor(monkeypatch, ["injection.heuristic", "pii.native", "no.such.detector"])
    detectors = checks["detectors"]
    assert detectors["state"] == "warn"
    assert "2 running: injection.heuristic, pii.native" in detectors["detail"]
    assert "no.such.detector" in detectors["detail"]
    # Available but not enabled is not running, and is not listed as if it were.
    assert "pii.presidio" not in detectors["detail"].split(";")[0]


def test_doctor_is_green_when_every_enabled_detector_runs(monkeypatch):
    checks = _doctor(monkeypatch, ["injection.heuristic", "pii.native"])
    assert checks["detectors"]["state"] == "ok"
    assert "unavailable" not in checks["detectors"]["detail"]


def test_doctor_says_offline_only_when_only_echo_is_available(monkeypatch):
    providers = _doctor(monkeypatch)["providers"]
    assert "offline only" in providers["detail"]
    assert "AGENTFOX_ALLOW_EGRESS" in providers["detail"]


# --- test action ------------------------------------------------------------


def test_test_action_without_sqlglot_keeps_the_install_hint(monkeypatch):
    import agentfox.capabilities.detection.actions as actions

    monkeypatch.setattr(actions, "SQLGLOT_AVAILABLE", False)
    result = runner.invoke(app, ["test", "action", "DELETE FROM users"])
    output = flat(result.output)
    assert result.exit_code == 1
    assert "pip install 'agentfox[sql]'" in output
    assert "reversibility unknown" in output
    assert " reversible " not in f" {output} "


# --- policy rules apply --agent unknown -------------------------------------


def test_rules_apply_with_an_unknown_agent_is_a_message_not_a_traceback(tmp_path):
    _seed()
    ladder = tmp_path / "ladder.yaml"
    ladder.write_text(
        "key: refund-ladder\ntool: payments.refund\nfield: arguments.amount\nunit: USD\n"
        "bands:\n  - {upto: 10, outcome: allow}\n  - {outcome: escalate}\n"
    )
    result = runner.invoke(app, ["policy", "rules", "apply", str(ladder), "--agent", "nobody"])
    assert result.exit_code == 1
    assert isinstance(result.exception, SystemExit)
    output = flat(result.output)
    assert "unknown agent 'nobody'" in output
    assert "support-triage" in output  # names the real ones
    assert "Traceback" not in result.output


# --- init / database errors -------------------------------------------------


def test_init_with_a_missing_path_is_a_message_not_a_traceback(tmp_path):
    missing = tmp_path / "does" / "not" / "exist"
    result = runner.invoke(app, ["init", "--path", str(missing)])
    assert result.exit_code == 2
    assert isinstance(result.exception, SystemExit)
    assert "is not a directory" in flat(result.output)


def test_an_sql_ascii_database_gets_a_readable_message(tmp_path, monkeypatch):
    import agentfox.core.db as db
    from agentfox.cli.onboarding import database_error_hint

    hint = database_error_hint(TypeError("cannot use a string pattern on a bytes-like object"))
    assert "UTF8" in hint and "SQL_ASCII" in hint

    def broken(*args, **kwargs):
        raise TypeError("cannot use a string pattern on a bytes-like object")

    monkeypatch.setattr(db, "init_db", broken)
    result = runner.invoke(app, ["init", "--path", str(tmp_path)])
    assert result.exit_code == 1
    assert isinstance(result.exception, SystemExit)
    assert "UTF8" in flat(result.output)


# --- agents register / budget -----------------------------------------------


def test_agents_register_creates_an_owned_agent_and_keeps_unset_fields():
    from agentfox.core.db import session_scope
    from agentfox.core.models import Agent

    result = runner.invoke(
        app,
        [
            "agents",
            "register",
            "billing-bot",
            "--name",
            "Billing bot",
            "--owner",
            "ops@example.com",
            "--env",
            "staging",
        ],
    )
    assert result.exit_code == 0, result.output
    again = runner.invoke(app, ["agents", "register", "billing-bot", "--risk-tier", "high"])
    assert again.exit_code == 0, again.output
    with session_scope() as session:
        agent = session.scalar(select(Agent).where(Agent.slug == "billing-bot"))
        assert agent.registered
        assert agent.owner_email == "ops@example.com"
        assert agent.environment == "staging"  # not reset by the second call
        assert agent.risk_tier == "high"


def test_agents_budget_sets_and_shows_caps_the_runtime_enforces():
    from agentfox.core.db import session_scope
    from agentfox.core.models import Agent, Budget
    from agentfox.runtime.reliability import check_budget

    runner.invoke(app, ["agents", "register", "billing-bot"])
    result = runner.invoke(
        app, ["agents", "budget", "billing-bot", "--max-calls", "2", "--window", "day"]
    )
    assert result.exit_code == 0, result.output
    assert "2" in result.output and "per day" in result.output

    with session_scope() as session:
        agent = session.scalar(select(Agent).where(Agent.slug == "billing-bot"))
        budget = session.scalar(select(Budget).where(Budget.scope_id == agent.id))
        assert (budget.max_calls, budget.window) == (2, "day")
        budget.calls = 2
        assert check_budget(session, "agent", agent.id).exceeded

    shown = runner.invoke(app, ["agents", "budget", "billing-bot"])
    assert "2 / 2" in flat(shown.output)

    cleared = runner.invoke(app, ["agents", "budget", "billing-bot", "--clear"])
    assert cleared.exit_code == 0
    with session_scope() as session:
        assert session.scalar(select(Budget)) is None


@pytest.mark.parametrize(
    "args",
    [
        ["agents", "budget", "nobody", "--max-calls", "1"],
        ["agents", "budget", "billing-bot", "--window", "fortnight"],
        ["agents", "register", "x", "--risk-tier", "extreme"],
    ],
)
def test_agents_budget_and_register_refuse_bad_input(args):
    runner.invoke(app, ["agents", "register", "billing-bot"])
    result = runner.invoke(app, args)
    assert result.exit_code in (1, 2)
    assert isinstance(result.exception, SystemExit)
