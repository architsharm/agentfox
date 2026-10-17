"""#10/#61/#71: a fresh self-hosted database can get its first operator without demo data.

Before: `admin auth issue` on a fresh database failed "unknown user", and the only ways
to create one were GitHub sign-in or `admin seed`, which also loads demo agents and
traffic into what is meant to be a production database.
Also #22: `admin auth status` advises the AGENTFOX_* variables.
"""

from __future__ import annotations

import re

from sqlalchemy import select
from typer.testing import CliRunner

from agentfox.apps.cli.main import app
from agentfox.core.db import session_scope
from agentfox.core.models import Agent, User
from agentfox.core.tenancy import system_scope

runner = CliRunner()


def flat(output: str) -> str:
    return " ".join(output.split())


def test_first_operator_on_a_fresh_database_without_demo_data():
    issue = runner.invoke(app, ["admin", "auth", "issue", "ops@corp.example"])
    assert issue.exit_code == 1
    assert "admin users create ops@corp.example" in flat(issue.output)

    created = runner.invoke(
        app, ["admin", "users", "create", "ops@corp.example", "--role", "owner"]
    )
    assert created.exit_code == 0, created.output
    assert "owner" in created.output

    issued = runner.invoke(app, ["admin", "auth", "issue", "ops@corp.example"])
    assert issued.exit_code == 0, issued.output
    assert re.search(r"nom_api_\w{20,}", issued.output)

    with system_scope("test"), session_scope() as s:
        assert s.scalar(select(User).where(User.email == "ops@corp.example")).role == "owner"
        assert s.scalars(select(Agent)).all() == [], "no demo data may be loaded"


def test_users_create_can_issue_the_token_in_one_step():
    result = runner.invoke(app, ["admin", "users", "create", "a@corp.example", "--token"])
    assert result.exit_code == 0, result.output
    assert re.search(r"nom_api_\w{20,}", result.output)


def test_users_create_refuses_a_duplicate_and_an_unknown_role():
    assert runner.invoke(app, ["admin", "users", "create", "b@corp.example"]).exit_code == 0
    again = runner.invoke(app, ["admin", "users", "create", "b@corp.example"])
    assert again.exit_code == 1
    assert "already exists" in again.output
    bad = runner.invoke(app, ["admin", "users", "create", "c@corp.example", "--role", "god"])
    assert bad.exit_code == 2
    assert "unknown role" in bad.output


def test_users_create_is_audited():
    from agentfox.core.models import AuditEntry

    runner.invoke(app, ["admin", "users", "create", "d@corp.example"])
    with system_scope("test"), session_scope() as s:
        actions = [e.action for e in s.scalars(select(AuditEntry))]
    assert "operator.user.created" in actions


def test_auth_status_advises_agentfox_variables():
    result = runner.invoke(app, ["admin", "auth", "status"])
    assert result.exit_code == 0, result.output
    assert "AGENTFOX_ENVIRONMENT=production" in flat(result.output)
