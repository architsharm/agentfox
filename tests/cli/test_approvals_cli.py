"""`agentfox permit approvals` — the queue of held calls, from the CLI (#15).

The getting-started guide said an approval could be decided "from the dashboard or
the CLI", and there was no CLI.
"""

from __future__ import annotations

import json

from typer.testing import CliRunner

from agentfox.cli.main import app
from agentfox.identity import request_approval

runner = CliRunner()


def _file(session, tool="email.send"):
    approval = request_approval(
        session,
        agent_id=None,
        tool_key=tool,
        arguments={"to": "customer@example.com"},
        reason="The granting capability requires human approval for this action.",
    )
    session.commit()
    return approval.id


def test_list_show_approve_and_deny(session):
    first, second = _file(session), _file(session, "billing.export")

    listed = runner.invoke(app, ["permit", "approvals", "list", "--json"])
    assert listed.exit_code == 0, listed.output
    rows = {r["id"]: r for r in json.loads(listed.output)}
    assert set(rows) == {first, second}
    assert rows[first]["arguments"] == {"to": "customer@example.com"}

    shown = runner.invoke(app, ["permit", "approvals", "show", first])
    assert shown.exit_code == 0, shown.output
    assert "email.send" in shown.output and "customer@example.com" in shown.output

    approved = runner.invoke(
        app,
        ["permit", "approvals", "approve", first[-8:], "-r", "ticket 4411", "--as", "m@x.io"],
    )
    assert approved.exit_code == 0, approved.output
    assert "approved" in approved.output
    denied = runner.invoke(app, ["permit", "approvals", "deny", second])
    assert denied.exit_code == 0, denied.output

    by_status = json.loads(
        runner.invoke(app, ["permit", "approvals", "list", "--status", "all", "--json"]).output
    )
    status = {r["id"]: (r["status"], r["resolver"], r["rationale"]) for r in by_status}
    assert status[first] == ("approved", "m@x.io", "ticket 4411")
    assert status[second][0] == "denied"

    # A decided approval is not decided twice.
    again = runner.invoke(app, ["permit", "approvals", "deny", first])
    assert again.exit_code == 1
    assert "already approved" in again.output


def test_an_unknown_approval_is_named(session):
    result = runner.invoke(app, ["permit", "approvals", "approve", "apr_nope"])
    assert result.exit_code == 1
    assert "unknown approval" in result.output


def test_the_top_level_name_works_too(session):
    approval_id = _file(session)
    result = runner.invoke(app, ["permit", "approvals", "approve", approval_id])
    assert result.exit_code == 0, result.output
