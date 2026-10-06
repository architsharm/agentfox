"""Zero-effort onboarding: `agentfox init`, `check`, `doctor`, `findings`.

The rest of the CLI has forty commands across nine sub-apps, which is right for an
operator running a governance programme and wrong for the first ten minutes. Someone
evaluating this should type three words and understand their exposure — and every one
of those words has to be safe to run without reading the docs first.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from agentfox.apps.cli.main import app
from agentfox.capabilities.discovery.repo import ScanReport, Site, scan, scan_file
from tests.conftest import as_user

runner = CliRunner()


def flat(output: str) -> str:
    """Rich wraps to the terminal width, so a phrase can straddle a line break.

    Tests assert on meaning, not on layout.
    """
    return " ".join(output.split())


@pytest.fixture
def project(tmp_path) -> Path:
    (tmp_path / "app.py").write_text(
        "from openai import OpenAI\n"
        "client = OpenAI()\n"
        "def answer(q):\n"
        "    return client.chat.completions.create(model='gpt-4o', messages=[])\n"
    )
    (tmp_path / "worker.py").write_text(
        "import subprocess, anthropic\n"
        "c = anthropic.Anthropic()\n"
        "def summarise(t):\n"
        "    return c.messages.create(model='claude-sonnet-4', messages=[])\n"
        "def deploy():\n"
        "    subprocess.run(['./deploy.sh'])\n"
    )
    (tmp_path / ".mcp.json").write_text(
        '{"mcpServers": {"filesystem": {"command": "npx"}, "github": {"command": "npx"}}}'
    )
    return tmp_path


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def test_model_call_sites_are_found_across_providers(project):
    report = scan(project)
    providers = {s.provider for s in report.model_calls}
    assert providers == {"openai", "anthropic"}
    assert len(report.model_calls) == 2


def test_the_stack_is_reported(project):
    assert set(scan(project).frameworks) >= {"OpenAI SDK", "Anthropic SDK"}


def test_mcp_servers_are_found_in_config_not_code(project):
    """MCP servers are declared in config, so a code-only scan would miss every one."""
    servers = [s for s in scan(project).sites if s.kind == "mcp_server"]
    assert {s.detail.split("'")[1] for s in servers} == {"filesystem", "github"}


def test_shell_calls_are_flagged(project):
    assert any(s.kind == "shell_call" for s in scan(project).sites)


def test_a_governed_file_is_marked_as_such(tmp_path):
    (tmp_path / "main.py").write_text(
        "import agentfox\n"
        "agentfox.auto()\n"
        "from openai import OpenAI\n"
        "client = OpenAI()\n"
        "client.chat.completions.create(model='gpt-4o', messages=[])\n"
    )
    report = scan(tmp_path)
    assert report.model_calls[0].governed
    assert report.coverage == 1.0
    assert report.ungoverned == []


def test_common_method_names_do_not_become_findings(tmp_path):
    """`invoke` and `completion` are ordinary words. Without a model-ish keyword every
    .invoke() in a repo becomes a finding and the report gets ignored."""
    (tmp_path / "x.py").write_text(
        "handler.invoke()\nqueue.invoke(job)\nchain.invoke(input='hi')\n"
    )
    calls = scan(tmp_path).model_calls
    assert len(calls) == 1, [c.detail for c in calls]


def test_hard_coded_credentials_are_critical_and_never_echoed(tmp_path):
    """A scan report that reprints the key it found is a second copy of the leak."""
    secret = "sk-proj-AbCdEfGhIjKlMnOpQrStUv"
    (tmp_path / "conf.py").write_text(f'api_key = "{secret}"\n')
    sites = [s for s in scan(tmp_path).sites if s.kind == "secret"]
    assert sites and sites[0].severity == "critical"
    assert secret not in sites[0].detail


def test_inline_sql_is_flagged(tmp_path):
    (tmp_path / "db.py").write_text('cursor.execute(f"DELETE FROM users WHERE id={uid}")\n')
    assert any(s.kind == "sql_build" for s in scan(tmp_path).sites)


def test_tool_decorators_are_found(tmp_path):
    """An unregistered tool an agent can call is the blind spot the registry exists
    to close."""
    (tmp_path / "tools.py").write_text("@tool\ndef refund(amount):\n    pass\n")
    assert any(s.kind == "tool" for s in scan(tmp_path).sites)


def test_vendored_and_build_directories_are_skipped(tmp_path):
    for directory in ("node_modules", ".venv", "__pycache__"):
        target = tmp_path / directory
        target.mkdir()
        (target / "x.py").write_text("client.chat.completions.create(model='x')\n")
    assert scan(tmp_path).model_calls == []


def test_an_unparseable_file_is_reported_not_skipped(tmp_path):
    """An unparseable file is exactly where an ungoverned call would hide."""
    (tmp_path / "broken.py").write_text("def (((\n")
    report = scan(tmp_path)
    assert report.errors and "broken.py" in report.errors[0]


def test_scanning_never_imports_the_target(tmp_path):
    """Importing would execute arbitrary code from a repo the operator may not trust,
    and fail on anything with an import-time side effect."""
    (tmp_path / "boom.py").write_text("raise SystemExit('imported!')\n")
    assert scan(tmp_path).files_scanned == 1


def test_findings_are_ranked_by_what_to_look_at_first():
    """An alphabetical list of forty findings is the same as no list."""
    report = ScanReport(root=".")
    report.sites = [
        Site("model_call", "z.py", 1, "low", severity="info"),
        Site("secret", "a.py", 1, "leak", severity="critical"),
        Site("tool", "m.py", 1, "tool", severity="medium"),
    ]
    assert [s.severity for s in report.ranked()] == ["critical", "medium", "info"]


def test_the_report_ends_with_a_next_action(project):
    """A report that ends without one makes the reader do the synthesis, and most
    readers will not."""
    assert "agentfox.auto()" in scan(project).next_step()


def test_a_fully_governed_repo_says_so(tmp_path):
    (tmp_path / "m.py").write_text(
        "import agentfox\nagentfox.auto()\nc.messages.create(model='x', messages=[])\n"
    )
    assert "doctor" in scan(tmp_path).next_step()


def test_an_empty_repo_does_not_pretend(tmp_path):
    (tmp_path / "readme.py").write_text("x = 1\n")
    assert "No model calls found" in scan(tmp_path).next_step()


def test_scan_file_returns_its_own_pieces(project):
    sites, frameworks, governed = scan_file(project / "app.py", project)
    assert any(s.kind == "model_call" for s in sites)
    assert "OpenAI SDK" in frameworks
    assert governed is False


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_init_is_idempotent(isolated_db, tmp_path):
    """Safe to run twice is the property that lets someone try it without reading
    anything first."""
    first = runner.invoke(app, ["init", "--path", str(tmp_path)])
    second = runner.invoke(app, ["init", "--path", str(tmp_path)])
    assert first.exit_code == 0, first.output
    assert second.exit_code == 0, second.output
    assert (tmp_path / "agentfox.toml").exists()
    assert "already exists" in flat(second.output)


def test_init_leaves_an_existing_config_alone(isolated_db, tmp_path):
    (tmp_path / "agentfox.toml").write_text("# hand-edited\n")
    runner.invoke(app, ["init", "--path", str(tmp_path)])
    assert (tmp_path / "agentfox.toml").read_text() == "# hand-edited\n"


def test_init_loads_controls_and_policies_in_their_declared_modes(isolated_db, tmp_path):
    """Each pack is reported in the mode it actually binds in. A blanket "observe
    mode — nothing is blocked" was false: tool-containment ships `mode: enforce`."""
    result = runner.invoke(app, ["init", "--path", str(tmp_path)])
    output = flat(result.output)
    assert "controls" in output
    assert "baseline observe recorded, nothing blocked" in output
    assert "tool-containment enforce violations are blocked now" in output
    assert "nothing is blocked yet" not in output


def test_init_ends_by_telling_you_what_to_do_next(isolated_db, tmp_path):
    result = runner.invoke(app, ["init", "--path", str(tmp_path)])
    assert "agentfox scan" in flat(result.output)
    assert "agentfox.auto()" in flat(result.output)


def test_check_highlights_the_ungoverned_calls(isolated_db, project):
    result = runner.invoke(app, ["scan", "repo", str(project)])
    assert result.exit_code == 0
    assert "ungoverned" in flat(result.output)
    assert "app.py" in flat(result.output)


def test_check_can_gate_ci(isolated_db, project):
    """The same command a developer runs by hand is the one CI runs."""
    result = runner.invoke(app, ["scan", "repo", str(project), "--fail"])
    assert result.exit_code == 1


def test_check_passes_ci_when_everything_is_governed(isolated_db, tmp_path):
    (tmp_path / "m.py").write_text(
        "import agentfox\nagentfox.auto()\nc.messages.create(model='x', messages=[])\n"
    )
    assert runner.invoke(app, ["scan", "repo", str(tmp_path), "--fail"]).exit_code == 0


def test_check_emits_json_for_tooling(isolated_db, project):
    import json

    result = runner.invoke(app, ["scan", "repo", str(project), "--json"])
    payload = json.loads(result.output)
    assert payload["ungoverned_model_calls"] == 2
    assert payload["coverage"] == 0.0


def test_check_no_submit_never_touches_the_network(isolated_db, project, monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("httpx.post must not be called when --no-submit is passed")

    monkeypatch.setattr("agentfox.apps.cli.submit.httpx.post", _boom)
    result = runner.invoke(app, ["scan", "repo", str(project), "--no-submit"])
    assert result.exit_code == 0, result.output


def test_check_default_run_does_not_prompt_on_a_non_tty(isolated_db, project, monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("nothing should be submitted with no flag on a non-tty run")

    monkeypatch.setattr("agentfox.apps.cli.submit.httpx.post", _boom)
    result = runner.invoke(app, ["scan", "repo", str(project)])
    assert result.exit_code == 0, result.output
    assert "Submit to the dashboard?" not in result.output


def test_check_submit_sends_the_redacted_payload(isolated_db, project, monkeypatch):
    monkeypatch.setenv("NOMETRIA_API_URL", "https://plane.example.internal")
    monkeypatch.setenv("NOMETRIA_API_TOKEN", "nom_usr_test")
    captured = {}

    class _FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"scan_run_id": "scn_test", "summary": {"agents_proposed": ["myrepo-app"]}}

    def _fake_post(url, json, headers, timeout):
        captured["json"] = json
        return _FakeResponse()

    monkeypatch.setattr("agentfox.apps.cli.submit.httpx.post", _fake_post)
    result = runner.invoke(app, ["scan", "repo", str(project), "--submit"])
    assert result.exit_code == 0, result.output
    assert "Submitted." in flat(result.output)
    assert "deploy.sh" not in repr(captured["json"])  # worker.py's shell_call detail
    assert "detail" not in repr(captured["json"])
    assert "line" not in repr(captured["json"])


def test_doctor_reports_without_changing_anything(isolated_db):
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0
    assert "database" in flat(result.output)


def test_doctor_names_the_consequence_not_the_setting(isolated_db):
    """ "fail_mode=open" means nothing to someone who has not read the PRD."""
    result = runner.invoke(app, ["doctor"])
    assert "lets the request through" in flat(result.output)


def test_doctor_says_when_nothing_has_been_governed(isolated_db):
    result = runner.invoke(app, ["doctor"])
    assert "nothing has been governed yet" in flat(result.output)


def test_doctor_reports_the_enforce_observe_split_honestly(isolated_db):
    """A deployment where everything is observe-only is recorded, not protected, and
    doctor says so rather than reporting a green tick."""
    # Committed and closed: `doctor` opens its own session, so an uncommitted fixture
    # session would leave it looking at an empty database.
    from agentfox.core.db import session_scope
    from agentfox.fixtures.seed import seed
    from agentfox.runtime.enforcement import Enforcer

    with session_scope() as session:
        seed(session)
    with session_scope() as session:
        Enforcer(session).run_completion(
            agent_slug="support-triage",
            messages=[{"role": "user", "content": "hi"}],
            model="echo-1",
        )

    result = runner.invoke(app, ["doctor"])
    output = flat(result.output)
    assert "decisions enforced" in output or "not a finished configuration" in output


def test_findings_says_so_when_there_are_none(isolated_db):
    result = runner.invoke(app, ["findings"])
    assert result.exit_code == 0
    assert "No open findings" in flat(result.output)


def test_findings_lists_what_the_platform_found(isolated_db):
    from agentfox.core.db import session_scope
    from agentfox.core.models import Finding

    with session_scope() as session:
        session.add(
            Finding(
                type="missed_escalation",
                severity="high",
                title="Conversation qualified for a hand-off and never got one",
                subject_type="agent",
            )
        )
    result = runner.invoke(app, ["findings"])
    assert "missed_escalation" in flat(result.output)


def test_the_onboarding_verbs_are_top_level(isolated_db):
    """Buried under a sub-app they would not be found in the first ten minutes."""
    result = runner.invoke(app, ["--help"])
    for verb in ("init", "demo", "scan", "doctor", "findings"):
        assert verb in flat(result.output)


# ---------------------------------------------------------------------------
# The control-plane entry experience
# ---------------------------------------------------------------------------


def test_the_checklist_is_computed_from_live_data(client):
    """A checklist that can disagree with the system is worse than none, so no step
    is ever a stored "completed" flag."""
    body = client.get("/api/onboarding", headers=as_user("admin@example.com")).json()
    assert body["total"] == 7
    install = next(s for s in body["steps"] if s["id"] == "install")
    assert install["done"] is True, "the seeded fixture has agents"
    # "connect" (GitHub) sits right after "install" and is unmet by the seeded
    # fixture — no connection exists until someone actually connects a repo.
    assert body["next"]["id"] == "connect"


def test_not_connected_and_nothing_wrong_are_distinguishable(client):
    """Zero of everything looks identical whether nothing is wrong or nothing is
    connected, and only one of those is good news."""
    body = client.get("/api/onboarding", headers=as_user("admin@example.com")).json()
    assert body["connected"] is False

    from agentfox.core.db import session_scope
    from agentfox.runtime.enforcement import Enforcer

    with session_scope() as session:
        Enforcer(session).run_completion(
            agent_slug="support-triage",
            messages=[{"role": "user", "content": "hi"}],
            model="echo-1",
        )
    after = client.get("/api/onboarding", headers=as_user("admin@example.com")).json()
    assert after["connected"] is True


def test_enforcement_is_the_last_step(client):
    """Promotes the content-based policies from observe to enforce.

    Tool containment is a separate, structural policy that already enforces from
    step 1 — this step is about the content-based policies specifically, not "the
    only thing that blocks anything" (that claim was inaccurate and got corrected
    after a UX audit caught it contradicting the Policies page).
    """
    body = client.get("/api/onboarding", headers=as_user("admin@example.com")).json()
    assert body["steps"][-1]["id"] == "enforce"
    assert "observe to enforce" in body["steps"][-1]["detail"]


def test_attention_is_quiet_when_there_is_nothing_to_do(client):
    body = client.get("/api/attention", headers=as_user("admin@example.com")).json()
    assert body["quiet"] is True
    assert body["items"] == []


def test_attention_ranks_by_severity(client):
    from agentfox.core.db import session_scope
    from agentfox.core.models import Finding

    with session_scope() as session:
        session.add(
            Finding(type="a", severity="medium", title="medium thing", subject_type="agent")
        )
        session.add(
            Finding(type="b", severity="critical", title="critical thing", subject_type="agent")
        )

    body = client.get("/api/attention", headers=as_user("admin@example.com")).json()
    assert body["items"][0]["severity"] == "critical"
    assert body["counts"]["critical"] == 1


def test_a_breached_handoff_outranks_most_findings(client):
    """A hand-off past its SLA is a person waiting."""
    from agentfox.core.db import session_scope
    from agentfox.core.models import Handoff

    with session_scope() as session:
        session.add(Handoff(session_id="s-1", status="breached", owner_role="support", reason="x"))

    body = client.get("/api/attention", headers=as_user("admin@example.com")).json()
    assert any(i["type"] == "handoff_sla_breach" for i in body["items"])


def test_every_attention_item_links_somewhere(client):
    from agentfox.core.db import session_scope
    from agentfox.core.models import Finding

    with session_scope() as session:
        session.add(Finding(type="a", severity="high", title="t", subject_type="agent"))

    body = client.get("/api/attention", headers=as_user("admin@example.com")).json()
    assert all(i["href"].startswith("/") for i in body["items"])


def test_a_finding_alert_links_to_its_own_detail_page_not_the_general_queue(client):
    """A homepage alert that links to the generic list makes the reader re-find the
    exact thing they just clicked on among identical-looking rows."""
    from agentfox.core.db import session_scope
    from agentfox.core.models import Finding

    with session_scope() as session:
        finding = Finding(type="a", severity="critical", title="t", subject_type="agent")
        session.add(finding)
        session.flush()
        finding_id = finding.id

    body = client.get("/api/attention", headers=as_user("admin@example.com")).json()
    item = next(i for i in body["items"] if i["type"] == "a")
    assert item["href"] == f"/app/findings/{finding_id}"


def test_me_returns_the_signed_in_identity(client):
    """The account menu needs a real answer to 'who am I, whose data is this' —
    not just a bare 'Sign out' link."""
    body = client.get("/api/me", headers=as_user("admin@example.com")).json()
    assert body["email"] == "admin@example.com"
    assert body["org_id"]
    assert "workspace" in body
