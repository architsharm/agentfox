"""One key everywhere: with an account key configured, the CLI reads and writes the
account through its gateway, not this machine's database, and says which it is using.

The gateway is the real one, in-process (`client`), sharing the test database. The CLI
reaches it over `httpx` with the key, exactly as it would reach Cloud: the requests are
recorded, so each test checks both what the command printed and that the account (not
a local session) answered it.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from sqlalchemy import select
from typer.testing import CliRunner

from agentfox.apps.cli import account as account_mod
from agentfox.apps.cli.main import app
from agentfox.apps.cli.wizard.backend import Remote
from agentfox.core.db import session_scope
from agentfox.core.models import Agent, ApprovalRequest, Finding, User

runner = CliRunner()


@pytest.fixture
def account(client, monkeypatch):
    """A workspace key in the environment, and every account request sent to the
    in-process gateway. Returns the (method, path) pairs the CLI asked for."""
    from agentfox.platform.identity.operators import issue_token

    with session_scope() as session:
        user = session.scalar(select(User).where(User.email == "admin@example.com"))
        _token, raw = issue_token(session, user, name="laptop")

    calls: list[tuple[str, str]] = []

    class Wire:
        def request(self, method, url, **kwargs):
            calls.append((method, url.removeprefix("http://testserver").split("?")[0]))
            return client.request(method, url, **kwargs)

    def remote(self):
        if self._remote is None:
            self._remote = Remote(self.url, self.key, client=Wire())
        return self._remote

    monkeypatch.setattr(account_mod.Account, "remote", property(remote))
    monkeypatch.setenv("AGENTFOX_URL", "http://testserver")
    monkeypatch.setenv("AGENTFOX_API_KEY", raw)
    # The database stays the test's (the engine is already bound); only the explicit
    # variable that means "use this database directly" goes away.
    monkeypatch.delenv("AGENTFOX_DATABASE_URL")
    return calls


def _agent_id(slug: str) -> str:
    with session_scope() as session:
        return session.scalar(select(Agent.id).where(Agent.slug == slug))


def test_findings_come_from_the_account_and_say_so(account):
    with session_scope() as session:
        session.add(
            Finding(
                type="exfiltration.tool_call",
                severity="high",
                title="Customer data sent to an outside address",
                subject_type="agent",
                subject_id="support-triage",
                status="open",
            )
        )

    result = runner.invoke(app, ["findings"])

    assert result.exit_code == 0, result.output
    assert "Account: http://testserver (workspace" in result.output
    assert "Customer data" in result.output
    assert ("GET", "/api/findings") in account
    # The local control plane hint is wrong for an account user.
    assert "agentfox serve" not in result.output


def test_json_output_stays_clean(account):
    result = runner.invoke(app, ["findings", "--json"])
    assert result.exit_code == 0, result.output
    json.loads(result.stdout)
    assert ("GET", "/api/findings") in account


def test_agents_list_is_the_accounts(account):
    result = runner.invoke(app, ["agents", "list"])
    assert result.exit_code == 0, result.output
    assert "support-triage" in result.output
    assert ("GET", "/api/agents") in account


def test_permit_grant_list_revoke_go_through_the_account(account):
    grant = runner.invoke(
        app,
        ["permit", "grant", "support-triage", "crm.lookup", "--limit", "amount:lt=100", "--yes"],
    )
    assert grant.exit_code == 0, grant.output
    assert ("POST", "/api/agents/support-triage/access") in account

    listed = runner.invoke(app, ["permit", "list", "support-triage", "--json"])
    assert listed.exit_code == 0, listed.output
    rows = json.loads(listed.stdout)
    row = next(r for r in rows if r["tool_key"] == "crm.lookup")
    assert row["constraints"] == {"amount": {"lt": 100}}

    revoked = runner.invoke(app, ["permit", "revoke", row["id"], "--yes"])
    assert revoked.exit_code == 0, revoked.output
    assert ("DELETE", f"/api/agents/support-triage/access/{row['id']}") in account
    again = json.loads(runner.invoke(app, ["permit", "list", "support-triage", "--json"]).stdout)
    assert all(r["tool_key"] != "crm.lookup" for r in again)


def test_unknown_agent_on_the_account_names_the_real_ones(account):
    result = runner.invoke(app, ["permit", "grant", "nobody", "crm.lookup", "--yes"])
    assert result.exit_code == 1
    assert "unknown agent 'nobody'" in result.output
    assert "support-triage" in result.output


def test_approvals_are_listed_and_decided_on_the_account(account):
    with session_scope() as session:
        approval = ApprovalRequest(
            agent_id=_agent_id("support-triage"),
            tool_key="payments.transfer",
            arguments_json={"amount": 900},
            reason="over the limit",
        )
        session.add(approval)
        session.flush()
        approval_id = approval.id

    listed = runner.invoke(app, ["permit", "approvals", "list", "--json"])
    assert listed.exit_code == 0, listed.output
    assert [r["id"] for r in json.loads(listed.stdout)] == [approval_id]

    decided = runner.invoke(app, ["permit", "approvals", "approve", approval_id[-8:]])
    assert decided.exit_code == 0, decided.output
    assert "approved" in decided.output
    assert ("POST", f"/api/approvals/{approval_id}/approve") in account
    with session_scope() as session:
        assert session.get(ApprovalRequest, approval_id).status == "approved"


def test_declare_tool_and_list_on_the_account(account):
    result = runner.invoke(
        app,
        [
            "declare",
            "tool",
            "billing.refund",
            "--impact",
            "irreversible",
            "--triggers",
            "ledger.post",
        ],
    )
    assert result.exit_code == 0, result.output
    assert ("POST", "/api/tools") in account

    listed = runner.invoke(app, ["declare", "list", "tools", "--json"])
    rows = json.loads(listed.stdout)
    refund = next(r for r in rows if r["key"] == "billing.refund")
    assert refund["impact"] == "irreversible"
    assert refund["triggers"] == ["ledger.post"]


def test_policy_enforce_on_the_account_needs_a_simulation_first(account):
    """The dashboard refuses Start blocking until the rules were replayed; the CLI
    going through the account is held to the same gate."""
    listed = runner.invoke(app, ["policy", "list"])
    assert listed.exit_code == 0, listed.output
    assert ("GET", "/api/policies") in account
    key = "tool-containment"

    refused = runner.invoke(app, ["policy", "enforce", key])
    assert refused.exit_code == 1, refused.output
    assert "has not been simulated yet" in refused.output
    assert f"agentfox policy simulate {key}" in refused.output

    simulated = runner.invoke(app, ["policy", "simulate", key])
    assert ("POST", "/api/policies/simulate") in account, simulated.output

    enforced = runner.invoke(app, ["policy", "enforce", key])
    assert enforced.exit_code == 0, enforced.output
    assert "enforce" in enforced.output


def test_policy_effective_and_suites_and_verify(account):
    effective = runner.invoke(app, ["policy", "effective", "--agent", "support-triage"])
    assert effective.exit_code == 0, effective.output
    assert ("GET", "/api/policies/effective") in account

    suites = runner.invoke(app, ["test", "suites"])
    assert suites.exit_code == 0, suites.output
    assert ("GET", "/api/eval/suites") in account

    verify = runner.invoke(app, ["report", "verify"])
    assert verify.exit_code == 0, verify.output
    assert "CHAIN INTACT" in verify.output
    assert ("POST", "/api/audit/verify") in account


def test_report_summary_comes_from_the_account(account):
    result = runner.invoke(app, ["report", "summary"])
    assert result.exit_code == 0, result.output
    assert ("GET", "/api/report/summary") in account


def test_a_rejected_key_is_one_line_naming_the_fix(account, monkeypatch):
    monkeypatch.setenv("AGENTFOX_API_KEY", "nom_api_wrong")
    result = runner.invoke(app, ["findings"])
    assert result.exit_code == 1
    assert "rejected your AgentFox key (401)" in result.output
    assert "Create a key" in result.output
    assert "Traceback" not in result.output


def test_without_a_key_the_local_database_is_used_and_named(monkeypatch, tmp_path):
    monkeypatch.delenv("AGENTFOX_API_KEY", raising=False)
    monkeypatch.delenv("AGENTFOX_URL", raising=False)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["findings"])
    assert result.exit_code == 0, result.output
    # The test's database is an explicit AGENTFOX_DATABASE_URL: named as such.
    assert "Database: sqlite" in result.output or "Local:" in result.output


def test_the_project_env_file_is_an_account_too(account, monkeypatch, tmp_path):
    """`.agentfox/agentfox.env` (what init/up/login write) is read like the environment."""
    from agentfox.capabilities.onboarding.project_files import write_env

    raw = os.environ["AGENTFOX_API_KEY"]
    monkeypatch.delenv("AGENTFOX_API_KEY")
    monkeypatch.delenv("AGENTFOX_URL")
    write_env(tmp_path, {"AGENTFOX_URL": "http://testserver", "AGENTFOX_API_KEY": raw})
    monkeypatch.chdir(tmp_path)
    found = account_mod.configured()
    assert found is not None and found.origin == str(Path(".agentfox") / "agentfox.env")
    result = runner.invoke(app, ["agents", "list"])
    assert result.exit_code == 0, result.output
    assert "Account: http://testserver" in result.output


def test_doctor_checks_the_account_server_and_key(account):
    result = runner.invoke(app, ["doctor", "--json"])
    checks = {c["check"]: c for c in json.loads(result.stdout)}
    assert checks["account"]["state"] == "ok"
    assert "workspace" in checks["account"]["detail"]
    assert ("GET", "/api/me") in account


def test_doctor_fails_loudly_on_a_bad_key(account, monkeypatch):
    monkeypatch.setenv("AGENTFOX_API_KEY", "nom_api_wrong")
    result = runner.invoke(app, ["doctor", "--json"])
    assert result.exit_code == 1
    checks = {c["check"]: c for c in json.loads(result.stdout)}
    assert checks["account"]["state"] == "bad"
    assert "rejected your AgentFox key" in checks["account"]["detail"]


def test_login_checks_the_key_and_saves_it_where_init_does(account, tmp_path):
    result = runner.invoke(app, ["login", "--path", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "workspace" in result.output
    assert ("GET", "/api/me") in account
    env = (tmp_path / ".agentfox" / "agentfox.env").read_text()
    assert env.startswith("# Written by `agentfox login`.")
    assert "AGENTFOX_URL=http://testserver" in env
    assert oct((tmp_path / ".agentfox" / "agentfox.env").stat().st_mode & 0o777) == "0o600"


def test_login_with_a_wrong_key_saves_nothing(account, monkeypatch, tmp_path):
    monkeypatch.setenv("AGENTFOX_API_KEY", "nom_api_wrong")
    result = runner.invoke(app, ["login", "--path", str(tmp_path)])
    assert result.exit_code == 1
    assert "rejected your AgentFox key (401)" in result.output
    assert not (tmp_path / ".agentfox" / "agentfox.env").exists()


def test_login_without_a_key_says_where_to_make_one(monkeypatch, tmp_path):
    monkeypatch.delenv("AGENTFOX_API_KEY", raising=False)
    monkeypatch.delenv("AGENTFOX_API_TOKEN", raising=False)
    result = runner.invoke(
        app, ["login", "--server", "https://gw.example", "--path", str(tmp_path)]
    )
    assert result.exit_code == 2
    assert "Get started → Create a key" in result.output


def test_agentfox_local_reads_this_machine_with_a_key_configured(account, monkeypatch):
    """What the coding-agent hooks record stays on this machine; in a project connected
    to an account, AGENTFOX_LOCAL=1 reads it."""
    monkeypatch.setenv("AGENTFOX_LOCAL", "1")
    result = runner.invoke(app, ["findings"])
    assert result.exit_code == 0, result.output
    assert "Local:" in result.output
    assert not account


def test_a_key_for_a_server_of_your_own_is_not_sent_to_clouds_pages(monkeypatch, tmp_path):
    from agentfox.apps.cli.account import keys_page
    from agentfox.apps.cli.wizard.targets import CLOUD_API_URL, CLOUD_APP_URL

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("AGENTFOX_DASHBOARD_URL", raising=False)
    monkeypatch.delenv("AGENTFOX_API_KEY", raising=False)
    monkeypatch.delenv("AGENTFOX_API_TOKEN", raising=False)
    result = runner.invoke(
        app, ["login", "--server", "http://127.0.0.1:8412", "--path", str(tmp_path)]
    )
    assert result.exit_code == 2
    flat = " ".join(result.output.split())
    assert "useagentfox.com" not in flat
    assert "dashboard for http://127.0.0.1:8412 (its address is not set here" in flat

    assert "useagentfox.com" not in keys_page("http://localhost:8080")
    assert keys_page(CLOUD_API_URL).endswith(f"({CLOUD_APP_URL}/app/start)")
    monkeypatch.setenv("AGENTFOX_DASHBOARD_URL", "https://agentfox.acme.test")
    assert "(https://agentfox.acme.test/app/start)" in keys_page("https://gw.acme.test")
