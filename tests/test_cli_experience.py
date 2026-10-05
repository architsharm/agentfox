"""Regressions for the command-line experience.

Each test names the thing that was wrong with what a user saw, so a future failure
reads as "that came back" rather than as an unexplained assertion.
"""

from __future__ import annotations

import json
import re

import pytest
from typer.testing import CliRunner

from agentfox.cli.main import app

runner = CliRunner()


def flat(output: str) -> str:
    return " ".join(output.split())


def _json(output: str):
    lines = [line for line in output.splitlines() if not line.startswith("INFO")]
    return json.loads("\n".join(lines))


def _seed() -> dict:
    from agentfox.core.db import session_scope
    from agentfox.core.seed import seed

    with session_scope() as session:
        return seed(session)


# ---------------------------------------------------------------------------
# 1. capability grants are reachable from the CLI at all
# ---------------------------------------------------------------------------


def test_capability_grant_writes_a_grant_the_engine_then_honours():
    """The whole point: the grant this command writes is the one `check_capability`
    reads. A command that only wrote a row would be worse than no command."""
    from sqlalchemy import select

    from agentfox.core.db import session_scope
    from agentfox.identity import check_capability, ensure_identity
    from agentfox.core.models import Agent

    _seed()
    result = runner.invoke(
        app,
        [
            "capability",
            "grant",
            "support-triage",
            "reports.export",
            "--action",
            "read",
            "--limit",
            "rows:lte=500",
            "--max-taint",
            "retrieved",
            "--yes",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "granted" in flat(result.output)

    with session_scope() as session:
        agent = session.scalar(select(Agent).where(Agent.slug == "support-triage"))
        identity = ensure_identity(session, agent)
        allowed = check_capability(session, identity, "reports.export", "read", {"rows": 100})
        assert allowed.granted, allowed.reasons
        over = check_capability(session, identity, "reports.export", "read", {"rows": 5000})
        assert not over.granted
        wrong_action = check_capability(session, identity, "reports.export", "delete", {"rows": 1})
        assert not wrong_action.granted


def test_capability_grant_asks_before_widening_what_an_agent_may_do():
    _seed()
    declined = runner.invoke(
        app, ["capability", "grant", "support-triage", "payments.transfer"], input="n\n"
    )
    assert declined.exit_code == 1
    assert "nothing granted" in flat(declined.output)

    listed = runner.invoke(app, ["capability", "list", "support-triage", "--json"])
    assert all(row["tool_key"] != "payments.transfer" for row in _json(listed.output))


def test_capability_grant_is_recorded_in_the_audit_chain():
    """Every other state-changing command in this CLI appends to the chain; a grant
    widens authority, so it is the last one that should be exempt."""
    from sqlalchemy import select

    from agentfox.prove.audit import chain
    from agentfox.core.db import session_scope
    from agentfox.core.models import AuditEntry

    _seed()
    runner.invoke(app, ["capability", "grant", "support-triage", "reports.export", "--yes"])
    with session_scope() as session:
        kinds = [e.action for e in session.scalars(select(AuditEntry))]
        assert "capability.granted" in kinds
        assert chain.verify_range(session).valid


def test_capability_grant_expiry_stops_the_grant_matching():
    import datetime as dt

    from sqlalchemy import select

    from agentfox.core.db import session_scope
    from agentfox.identity import check_capability, ensure_identity
    from agentfox.core.models import Agent, Capability, utcnow

    _seed()
    runner.invoke(
        app,
        [
            "capability",
            "grant",
            "support-triage",
            "reports.export",
            "--expires-in-days",
            "7",
            "--yes",
        ],
    )
    with session_scope() as session:
        agent = session.scalar(select(Agent).where(Agent.slug == "support-triage"))
        identity = ensure_identity(session, agent)
        assert check_capability(session, identity, "reports.export").granted

        grant = session.scalar(select(Capability).where(Capability.tool_key == "reports.export"))
        assert grant.expires_at is not None
        grant.expires_at = utcnow() - dt.timedelta(days=1)
        session.flush()
        assert not check_capability(session, identity, "reports.export").granted


def test_capability_revoke_takes_the_permission_away_and_audits_it():
    from sqlalchemy import select

    from agentfox.core.db import session_scope
    from agentfox.identity import check_capability, ensure_identity
    from agentfox.core.models import Agent, AuditEntry

    _seed()
    runner.invoke(app, ["capability", "grant", "support-triage", "reports.export", "--yes"])
    listed = _json(runner.invoke(app, ["capability", "list", "--json"]).output)
    grant_id = next(r["id"] for r in listed if r["tool_key"] == "reports.export")

    result = runner.invoke(app, ["capability", "revoke", grant_id, "--yes"])
    assert result.exit_code == 0, result.output
    with session_scope() as session:
        agent = session.scalar(select(Agent).where(Agent.slug == "support-triage"))
        identity = ensure_identity(session, agent)
        assert not check_capability(session, identity, "reports.export").granted
        kinds = [e.action for e in session.scalars(select(AuditEntry))]
        assert "capability.revoked" in kinds


def test_capability_revoke_accepts_the_short_id_the_table_prints():
    from agentfox.cli._style import short_id

    _seed()
    runner.invoke(app, ["capability", "grant", "support-triage", "reports.export", "--yes"])
    listed = _json(runner.invoke(app, ["capability", "list", "--json"]).output)
    grant_id = next(r["id"] for r in listed if r["tool_key"] == "reports.export")

    result = runner.invoke(app, ["capability", "revoke", short_id(grant_id), "--yes"])
    assert result.exit_code == 0, result.output
    assert "revoked" in flat(result.output)


def test_capability_grant_names_the_known_agents_when_the_slug_is_wrong():
    _seed()
    result = runner.invoke(app, ["capability", "grant", "nosuch", "tool.x", "--yes"])
    assert result.exit_code == 1
    output = flat(result.output)
    assert "unknown agent 'nosuch'" in output
    assert "support-triage" in output


def test_capability_grant_refuses_a_comparison_the_engine_cannot_evaluate():
    """A stored `{"nope": 3}` constraint would be skipped at decision time, so a grant
    that looks narrow would in fact be wide open."""
    _seed()
    result = runner.invoke(
        app,
        [
            "capability",
            "grant",
            "support-triage",
            "reports.export",
            "--limit",
            "rows:nope=3",
            "--yes",
        ],
    )
    assert result.exit_code != 0
    assert "unknown comparison 'nope'" in flat(result.output)


def test_capability_list_on_an_empty_set_names_the_command_that_fills_it():
    result = runner.invoke(app, ["capability", "list"])
    assert result.exit_code == 0, result.output
    assert "agentfox permit grant" in flat(result.output)


def test_doctor_names_the_capability_command_when_least_privilege_is_unconfigured():
    """doctor graded a deployment on capability grants while every sibling branch
    named a command and this one named none, because none existed."""
    from agentfox.core.db import session_scope
    from agentfox.core.models import Capability
    from agentfox.registry.service import upsert_tool

    with session_scope() as session:
        upsert_tool(session, "payments.transfer", impact="irreversible")
        assert session.query(Capability).count() == 0

    result = runner.invoke(app, ["doctor", "--json"])
    containment = next(c for c in _json(result.output) if c["check"] == "containment")
    assert "no capability grants" in containment["detail"]
    assert "agentfox permit grant" in containment["detail"]


# ---------------------------------------------------------------------------
# 2. findings is readable and ranked
# ---------------------------------------------------------------------------


def _raise_findings() -> None:
    from agentfox.core.db import session_scope
    from agentfox.prove.findings import raise_finding

    with session_scope() as session:
        raise_finding(
            session,
            type="unowned_agent",
            title="a medium one",
            severity="medium",
            subject_type="agent",
            subject_id="a1",
        )
        raise_finding(
            session,
            type="guardrail_detection",
            title="Blocked on tool_result: INJECTION.COVERT_INSTRUCTION, "
            "INJECTION.INSTRUCTION_OVERRIDE, INJECTION.ROLE_DELIMITER",
            severity="high",
            subject_type="agent",
            subject_id="a2",
        )
        raise_finding(
            session,
            type="stale_identity",
            title="another medium",
            severity="medium",
            subject_type="agent",
            subject_id="a3",
        )
        raise_finding(
            session,
            type="shadow_agent",
            title="a critical one",
            severity="critical",
            subject_type="agent",
            subject_id="a4",
        )


def test_findings_is_ordered_worst_first():
    """`agentfox check` advertises this list as ranked by severity and it was ordered
    by creation time: high, medium, medium, medium, high, high."""
    _raise_findings()
    result = runner.invoke(app, ["findings", "--json"])
    order = [row["severity"] for row in _json(result.output)]
    rank = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    assert order == sorted(order, key=lambda s: rank[s])
    assert order[0] == "critical"


def test_findings_ranks_before_it_limits():
    """Sorting a page the database happened to return would show the worst of twenty
    rows rather than the worst twenty rows."""
    from agentfox.core.db import session_scope
    from agentfox.prove.findings import raise_finding

    with session_scope() as session:
        for index in range(12):
            raise_finding(
                session,
                type="stale_identity",
                title=f"low {index}",
                severity="low",
                subject_type="agent",
                subject_id=f"low-{index}",
            )
        raise_finding(
            session,
            type="shadow_agent",
            title="the only critical",
            severity="critical",
            subject_type="agent",
            subject_id="crit",
        )

    rows = _json(runner.invoke(app, ["findings", "--limit", "3", "--json"]).output)
    assert rows[0]["severity"] == "critical"
    assert len(rows) == 3


def test_findings_shows_an_id_a_count_and_no_truncated_type():
    _raise_findings()
    result = runner.invoke(app, ["findings"])
    output = flat(result.output)
    # The type label used to be cut mid-token by a slice on the title.
    assert "INJECTION.INSTRUCTION_OVERRIDE" in output
    assert "INJECTION.INSTRUCTION_OVER " not in output
    # An id, shortened but present, so a row can be looked up.
    ids = {row["id"] for row in _json(runner.invoke(app, ["findings", "--json"]).output)}
    assert any(identifier[-8:] in output for identifier in ids)


def test_findings_surfaces_the_recurrence_count():
    """One problem seen forty times is not forty problems."""
    from agentfox.core.db import session_scope
    from agentfox.prove.findings import raise_finding

    with session_scope() as session:
        for _ in range(3):
            raise_finding(
                session,
                type="shadow_agent",
                title="the same problem",
                severity="high",
                subject_type="agent",
                subject_id="a1",
            )

    rows = _json(runner.invoke(app, ["findings", "--json"]).output)
    assert len(rows) == 1
    assert rows[0]["occurrences"] == 3
    assert "3x" in flat(runner.invoke(app, ["findings"]).output)


def test_findings_ends_with_a_next_panel_that_says_how_to_open_a_control_plane():
    """It used to end with "Full detail in the control plane" and no way to open one."""
    _raise_findings()
    output = flat(runner.invoke(app, ["findings"]).output)
    assert "Next" in output
    assert "agentfox serve" in output
    assert "Full detail in the control plane" not in output


def test_findings_options_carry_help_text():
    output = runner.invoke(app, ["findings", "--help"]).output
    for flag in ("--severity", "--limit", "--json"):
        line = next(ln for ln in output.splitlines() if flag in ln)
        # The description column used to be blank: "--severity  -s  TEXT".
        assert re.search(rf"{re.escape(flag)}\b.*[a-z]{{4,}}", line), line


def test_findings_rejects_a_severity_that_is_not_one():
    result = runner.invoke(app, ["findings", "--severity", "urgent"])
    assert result.exit_code == 2
    assert "critical" in flat(result.output)


# ---------------------------------------------------------------------------
# 3. check prints paths you can act on
# ---------------------------------------------------------------------------


def test_check_prints_whole_paths_or_shortens_them_from_the_left(tmp_path):
    """Paths rendered as "tests/test_discovery_submission.p…" cannot be copied or
    opened, which is the only reason to print them."""
    deep = tmp_path / "src" / "app" / "services" / "integrations" / "vendors"
    deep.mkdir(parents=True)
    (deep / "outbound_notification_dispatcher.py").write_text(
        "import openai\nopenai.chat.completions.create(model='gpt-4')\n"
    )
    output = flat(runner.invoke(app, ["check", str(tmp_path), "--no-submit"]).output)
    # The filename and its line number always survive.
    assert "outbound_notification_dispatcher.py:2" in output
    assert "dispatcher.p…" not in output


def test_check_marks_severity_with_a_word_not_only_a_colour(tmp_path):
    """Every severity rendered as the same dot, so a hard-coded credential looked
    like an ordinary call site in any terminal without colour."""
    (tmp_path / "leak.py").write_text('api_key = "sk-abcdefghijklmnopqrstuvwxyz"\n')
    (tmp_path / "call.py").write_text(
        "import openai\nopenai.chat.completions.create(model='gpt-4')\n"
    )
    result = runner.invoke(app, ["check", str(tmp_path), "--no-submit"])
    output = flat(result.output)
    assert "CRITICAL" in output
    assert "high" in output


def test_check_overflow_hint_is_a_command_that_runs(tmp_path):
    """ "… and 91 more (--limit)" is a flag name, not something anyone can run."""
    for index in range(8):
        (tmp_path / f"m{index}.py").write_text(
            "import openai\nopenai.chat.completions.create(model='gpt-4')\n"
        )
    result = runner.invoke(app, ["check", str(tmp_path), "--limit", "2", "--no-submit"])
    output = flat(result.output)
    assert "(--limit)" not in output
    hint = re.search(r"agentfox scan .*?--limit (\d+)", output)
    assert hint, output
    # The number in the hint is the number of sites, so running it shows all of them.
    rerun = runner.invoke(
        app,
        ["check", str(tmp_path), "--limit", hint.group(1), "--no-submit", "--json"],
    )
    assert rerun.exit_code == 0


def test_check_does_not_cut_a_finding_mid_word(tmp_path):
    """A row ending "(I-2 rug p" reads as a rendering fault, not as a finding."""
    (tmp_path / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"agentfox": {"command": "agentfox", "args": ["mcp"]}}})
    )
    output = flat(runner.invoke(app, ["check", str(tmp_path), "--no-submit"]).output)
    assert "change after you review them" in output
    # And the internal code the row used to end with is gone from what a user reads.
    assert "I-2" not in output


def test_check_still_promises_exactly_what_it_did_before(tmp_path):
    """The headline numbers and the Next panel are the best part of this command."""
    (tmp_path / "call.py").write_text(
        "import openai\nopenai.chat.completions.create(model='gpt-4')\n"
    )
    output = flat(runner.invoke(app, ["check", str(tmp_path), "--no-submit"]).output)
    assert "model call sites are ungoverned" in output
    assert "agentfox.auto()" in output


# ---------------------------------------------------------------------------
# 4. the demo does not contradict itself
# ---------------------------------------------------------------------------


@pytest.fixture
def walkthrough_output(capsys):
    from agentfox.cli import demo
    from agentfox.core.seed import register_scripts

    _seed()
    register_scripts()
    demo.run()
    return capsys.readouterr().out


def test_demo_prints_the_mode_of_the_rule_that_fired(walkthrough_output):
    """Section 03 printed `mode=enforce` for a rule belonging to a pack in observe,
    because the merged decision carries one mode for the whole call."""
    output = flat(walkthrough_output)
    assert "eu-ai-act-high-risk is in observe" in output
    assert "tool-containment is in enforce" in output
    assert "mode=enforce" not in output


def test_demo_labels_the_cold_start_and_prints_a_warm_number():
    """Section 01 printed ~3ms and section 09 ~2900ms for the same call, because the
    second included a one-time detector warm-up and said nothing about it."""
    from agentfox.cli.demo import _span_line

    steady = {"guard.input": 3.1, "guard.output": 2.9}
    cold_text, cold = _span_line(
        {"kind": "guardrail", "name": "guard.input", "duration_ms": 3509.1}, steady
    )
    assert cold
    assert "3509.1ms" in cold_text
    assert "first call only" in cold_text
    assert "3.1ms once warm" in cold_text

    warm_text, warm_cold = _span_line(
        {"kind": "guardrail", "name": "guard.output", "duration_ms": 2.9}, steady
    )
    assert not warm_cold
    assert "first call only" not in warm_text


def test_demo_does_not_cry_cold_start_over_ordinary_variance():
    from agentfox.cli.demo import _span_line

    _text, cold = _span_line(
        {"kind": "guardrail", "name": "guard.input", "duration_ms": 6.0},
        {"guard.input": 3.0},
    )
    assert not cold


def test_demo_measures_the_warm_figure_from_the_other_calls_in_the_run(walkthrough_output):
    """The claim "one-time warm-up" needs the same span on the calls that did not pay
    for it, not a constant."""
    from agentfox.cli.demo import _steady_state_spans
    from agentfox.core.db import session_scope

    with session_scope() as session:
        steady = _steady_state_spans(session, exclude_trace="no-such-trace")
    assert "guard.input" in steady
    assert steady["guard.input"] > 0


def test_demo_carries_no_number_it_did_not_derive(walkthrough_output):
    """Every other number in the walkthrough comes from the run; this one traced to an
    assertion in another module with no citation."""
    assert "78%" not in walkthrough_output


def test_demo_explains_why_the_framework_rows_match(walkthrough_output):
    output = flat(walkthrough_output)
    assert "map into every one of these frameworks" in output


def test_demo_only_explains_matching_rows_when_they_really_do_match():
    """The explanation is checked against the mappings, not asserted."""
    from sqlalchemy import select

    from agentfox.cli.demo import _shared_control_count
    from agentfox.core.db import session_scope
    from agentfox.core.models import FrameworkMapping

    _seed()
    with session_scope() as session:
        assert _shared_control_count(session, ("eu-ai-act", "soc2")) > 0
        one = session.scalars(
            select(FrameworkMapping).where(FrameworkMapping.framework == "soc2")
        ).first()
        session.delete(one)
        session.flush()
        assert _shared_control_count(session, ("eu-ai-act", "soc2")) == 0


# ---------------------------------------------------------------------------
# 5. first impressions
# ---------------------------------------------------------------------------


def test_seed_does_not_open_by_reading_as_a_failure():
    """ "controls 0 created, 317 mappings" is the normal result of a second run."""
    runner.invoke(app, ["seed"])
    output = flat(runner.invoke(app, ["seed"]).output)
    assert "0 created" not in output
    assert "framework mappings" in output


def test_seed_ends_with_a_next_panel_like_the_other_onboarding_commands():
    output = flat(runner.invoke(app, ["seed"]).output)
    assert "Next" in output
    assert "agentfox demo" in output


def test_policy_enforce_lists_the_valid_keys():
    _seed()
    result = runner.invoke(app, ["policy", "enforce", "nosuchpolicy"])
    assert result.exit_code == 1
    output = flat(result.output)
    assert "unknown policy 'nosuchpolicy'" in output
    assert "baseline" in output


def test_policy_enforce_still_promotes_a_real_policy():
    from agentfox.cli.demo import _current_mode

    _seed()
    assert runner.invoke(app, ["policy", "enforce", "baseline"]).exit_code == 0
    assert _current_mode("baseline") == "enforce"
    runner.invoke(app, ["policy", "observe", "baseline"])


def test_top_level_help_leads_with_what_a_command_does():
    """Internal taxonomy leaked into the first thing anyone reads."""
    # These three moved under `test` and `admin` in the CLI consolidation.
    output = "".join(runner.invoke(app, [group, "--help"]).output for group in ("test", "admin"))
    lines = {
        line.split()[1]: line
        for line in output.splitlines()
        if len(line.split()) > 2 and line.strip().startswith("│")
    }
    for name in ("action", "db", "version"):
        assert name in lines, output
    # A description may still cite a pillar, but it must not open with a code.
    assert not re.search(r"action\s+P9 —", output)
    assert "(PL-2)" not in output
    assert "(X-4)" not in output


def test_doctor_still_volunteers_its_own_failure_modes():
    """doctor reporting what is wrong with this deployment is the feature; none of
    the rewording above is allowed to soften it."""
    result = runner.invoke(app, ["doctor", "--json"])
    checks = {c["check"]: c for c in _json(result.output)}
    assert checks["authentication"]["state"] in ("warn", "bad")
    assert "anyone who can reach this port" in checks["authentication"]["detail"]
    assert checks["containment"]["state"] in ("warn", "bad")
