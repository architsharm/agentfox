"""P9 — action assurance.

Everything else governs the *call*. This governs the *artefact*: an agent holding a
legitimate `db.query` capability can pass `DROP TABLE users` as a well-formed string,
and every argument-level check passes it. An AI coding agent pointed at production
instead of staging wiped 1.9M rows exactly this way.

The target is zero false negatives on destructive operations. A false positive costs
an engineer a policy exception; a false negative costs a table.
"""

from __future__ import annotations

import datetime as dt

import pytest

from agentfox.core.models import Agent
from agentfox.detection.actions import (
    analyse_arguments,
    analyse_http,
    analyse_scope,
    analyse_shell,
    analyse_sql,
    environment_risk,
    summarise,
)
from agentfox.identity import ensure_identity, grant_capability

# ---------------------------------------------------------------------------
# Parsing: deterministic, never a model
# ---------------------------------------------------------------------------


def test_a_comment_cannot_smuggle_a_drop_past_the_parser():
    """`SELECT * FROM users -- ; DROP TABLE users` defeats keyword matching. To an AST
    it is one harmless SELECT, which is the correct reading."""
    analysis = analyse_sql("SELECT * FROM users -- ; DROP TABLE users")
    assert analysis.operation == "read"
    assert analysis.risks == []
    assert analysis.targets == ["users"], "the comment must not leak into the target name"


def test_unparseable_fails_closed(monkeypatch):
    """The adversarial input is precisely the one that fails to parse. Passing it
    through because analysis failed inverts the control."""
    analysis = analyse_sql("SELCT ** FROM (((")
    assert not analysis.parsed
    assert analysis.blocked
    assert analysis.risks[0].code == "sql.unparseable"


def test_analysis_without_sqlglot_refuses_rather_than_allows(monkeypatch):
    import agentfox.detection.actions as actions

    monkeypatch.setattr(actions, "SQLGLOT_AVAILABLE", False)
    analysis = actions.analyse_sql("SELECT 1")
    assert analysis.blocked
    assert analysis.risks[0].code == "analysis.unavailable"


# ---------------------------------------------------------------------------
# Classification and blast radius
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sql,operation",
    [
        ("SELECT id FROM users WHERE id = 1", "read"),
        ("UPDATE users SET name = 'x' WHERE id = 1", "write"),
        ("DROP TABLE users", "destructive"),
        ("TRUNCATE TABLE users", "destructive"),
        ("GRANT ALL ON users TO agent", "admin"),
    ],
)
def test_operations_are_classified_from_the_tree(sql, operation):
    assert analyse_sql(sql).operation == operation


def test_a_delete_with_no_where_is_the_1_9m_row_shape():
    analysis = analyse_sql("DELETE FROM users")
    assert analysis.blast_radius == "unbounded"
    assert not analysis.reversible
    assert [r.code for r in analysis.risks] == ["sql.unbounded_mutation"]


@pytest.mark.parametrize(
    "predicate",
    ["1 = 1", "'a' = 'a'", "TRUE", "id = id", "id = 5 OR 1 = 1"],
)
def test_a_tautology_is_unbounded_despite_having_a_where(predicate):
    """This is the shape that gets past "does it have a WHERE clause?"."""
    analysis = analyse_sql(f"DELETE FROM users WHERE {predicate}")
    assert analysis.blast_radius == "unbounded"
    assert [r.code for r in analysis.risks] == ["sql.tautological_predicate"]


def test_a_real_predicate_is_bounded():
    analysis = analyse_sql("DELETE FROM users WHERE id = 42")
    assert analysis.blast_radius == "bounded"
    assert analysis.risks == []


def test_stacked_statements_are_rejected():
    """No legitimate parameterised call needs two statements in one string."""
    analysis = analyse_sql("SELECT 1; DROP TABLE users")
    codes = [r.code for r in analysis.risks]
    assert "sql.stacked_statements" in codes
    assert "sql.destructive_ddl" in codes
    assert analysis.statements == 2


def test_a_privilege_change_is_never_merely_a_write():
    """An agent that can widen its own grants defeats every other control here."""
    analysis = analyse_sql("GRANT ALL ON users TO agent")
    assert [r.code for r in analysis.risks] == ["sql.privilege_change"]
    assert analysis.risks[0].severity == "high"


def test_ddl_is_flagged_irreversible():
    for sql in ("DROP TABLE users", "TRUNCATE TABLE users", "ALTER TABLE users DROP COLUMN ssn"):
        analysis = analyse_sql(sql)
        assert not analysis.reversible, sql
        assert analysis.blast_radius == "catastrophic", sql


# ---------------------------------------------------------------------------
# Environment binding (P9-6)
# ---------------------------------------------------------------------------


def test_the_same_statement_is_a_test_in_staging_and_an_incident_in_production():
    """The 1.9M-row incident was not an unusual statement. It was an ordinary one
    pointed at the wrong database."""
    analysis = analyse_sql("DELETE FROM users")
    assert environment_risk(analysis, "staging") is None
    risk = environment_risk(analysis, "production")
    assert risk is not None and risk.severity == "critical"


def test_a_bounded_reversible_statement_is_fine_in_production():
    assert environment_risk(analyse_sql("SELECT 1"), "production") is None
    assert environment_risk(analyse_sql("UPDATE t SET a=1 WHERE id=2"), "production") is None


# ---------------------------------------------------------------------------
# Non-SQL artefacts
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        "rm -rf /var/data",
        "sudo mkfs.ext4 /dev/sda1",
        "dd if=/dev/zero of=/dev/sda",
        "terraform destroy -auto-approve",
        "kubectl delete namespace production",
        "git push origin main --force",
    ],
)
def test_known_catastrophic_shell_shapes_are_caught(command):
    analysis = analyse_shell(command)
    assert analysis.blocked, command
    assert analysis.blast_radius == "catastrophic"


def test_ordinary_shell_is_not_flagged():
    """Shell has no sqlglot, so this is an explicit deny-list. It must not become a
    guessing game that blocks `ls`."""
    for command in ("ls -la", "cat README.md", "git status", "python -m pytest"):
        assert not analyse_shell(command).blocked, command


@pytest.mark.parametrize(
    "command",
    [
        "cd /tmp && rm -rf /important-data",
        "echo done; rm -rf /important-data",
        "true || rm -rf /important-data",
        "find . -name '*.tmp' | xargs rm -rf",
    ],
)
def test_a_destructive_command_chained_after_a_harmless_one_is_still_caught(command):
    """A single whole-string `.search()` already found these (it is not anchored to
    the start) — this instead proves segmentation reasons over the actual command
    boundaries rather than accidentally relying on that leniency."""
    assert analyse_shell(command).blocked, command


def test_an_operator_character_inside_a_quoted_string_is_not_a_false_segment_boundary():
    """`echo "a; b"` is one command, not two — a naive split on `;` without quote
    awareness would fracture it and could miss a destructive pattern that spans
    the quoted text's boundary in a more complex command."""
    from agentfox.detection.actions import _shell_segments

    assert _shell_segments('echo "a; b && c"') == ['echo "a; b && c"']


def test_a_quoted_mention_of_a_destructive_command_still_matches_todays_behavior():
    """Documents current, unchanged behavior rather than asserting a fix: the
    deny-list matches substrings regardless of quoting context, both before and
    after this change (distinguishing "mentioned in a string" from "executed" is
    a real shell-semantics problem this deny-list has never claimed to solve —
    see analyse_shell's own docstring)."""
    assert analyse_shell('echo "you should never run rm -rf /"').blocked


def test_http_reads_are_free_and_collection_deletes_are_not():
    assert analyse_http("GET", "/api/users").blast_radius == "none"
    assert analyse_http("DELETE", "/api/users/42").blast_radius == "bounded"
    collection = analyse_http("DELETE", "/api/users")
    assert collection.blast_radius == "unbounded"
    assert collection.risks[0].code == "http.collection_mutation"


# ---------------------------------------------------------------------------
# Argument dispatch and summary
# ---------------------------------------------------------------------------


def test_executable_arguments_are_found_by_their_declared_names():
    analyses = analyse_arguments({"query": "DELETE FROM users", "limit": 10})
    assert len(analyses) == 1 and analyses[0].blocked


def test_non_executable_arguments_are_left_alone():
    assert analyse_arguments({"note": "please clean up old files this week", "count": 3}) == []


def test_a_full_statement_pasted_into_an_ordinary_argument_is_caught():
    # "DELETE FROM users" is genuinely executable SQL regardless of what the field
    # is named — the exact shape benchmarks/action_safety/README.md's Dataset 4
    # named as the single largest miss category before this check existed.
    analyses = analyse_arguments({"note": "DELETE FROM users"})
    assert any(a.blocked for a in analyses)


def test_the_summary_takes_the_worst_of_several_artefacts():
    summary = summarise([analyse_sql("SELECT 1"), analyse_sql("DROP TABLE users")], "production")
    assert summary["operation"] == "destructive"
    assert summary["blast_radius"] == "catastrophic"
    assert not summary["reversible"]
    assert len(summary["critical"]) >= 1


def test_no_artefacts_means_no_summary():
    assert summarise([], "production") == {}


# ---------------------------------------------------------------------------
# Generic parameter scope anomalies — Tier C: over-privilege via ordinary params.
# The blueprint case: `look_up_order(order_id="*")` — a benign-sounding request
# translated into an over-broad tool call through a field no key-name dispatch
# (_SQL_KEYS/_SHELL_KEYS/_URL_KEYS) would ever look at.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["*", "%", "all", "ALL", "any", "everything"])
def test_wildcard_scope_values_are_flagged_critical(value):
    analysis = analyse_scope("order_id", value)
    assert analysis is not None
    assert analysis.blocked  # severity == critical, same tier as sql.destructive_ddl
    assert analysis.risks[0].code == "scope.wildcard_value"


def test_sql_fragment_in_an_arbitrary_field_is_still_caught():
    """`order_id` was never declared as a SQL parameter — `analyse_sql` never sees
    it — but the injected fragment is just as real."""
    analysis = analyse_scope("order_id", "1 OR 1=1")
    assert analysis is not None
    assert analysis.blocked
    assert analysis.risks[0].code == "scope.sql_fragment_in_value"


def test_path_traversal_in_an_arbitrary_field_is_flagged():
    analysis = analyse_scope("filename", "../../etc/passwd")
    assert analysis is not None
    assert analysis.risks[0].code == "scope.path_traversal"


@pytest.mark.parametrize(
    "value",
    [
        "12345",
        "ord_9f2a1c",
        "customer wants a refund on order 12345",
        "everything looks fine, please proceed",  # "everything" as a substring, not the whole value
    ],
)
def test_ordinary_values_are_not_flagged(value):
    assert analyse_scope("order_id", value) is None


def test_analyse_arguments_routes_unnamed_fields_through_scope_analysis():
    """The exact blueprint shape: a benign tool, an ordinary-named argument, an
    over-broad value — caught without the caller having declared `order_id` as
    anything special."""
    analyses = analyse_arguments({"order_id": "*"})
    assert len(analyses) == 1
    assert analyses[0].risks[0].code == "scope.wildcard_value"


# ---------------------------------------------------------------------------
# The enforcement path
# ---------------------------------------------------------------------------


@pytest.fixture
def db_agent(seeded):
    agent = seeded.query(Agent).filter_by(slug="support-triage").one()
    identity = ensure_identity(seeded, agent)
    grant_capability(seeded, identity, "db.query", max_taint="tool_result")
    return agent


def test_a_destructive_statement_is_blocked_through_a_granted_tool(seeded, enforcer, db_agent):
    """The whole point: the capability check passes and the call is still refused."""
    result = enforcer.guard_tool_call(
        agent_slug="support-triage",
        tool_key="db.query",
        arguments={"query": "DROP TABLE users"},
    )
    assert result.blocked
    assert result.taint["capability"]["granted"] is True, "the tool itself was authorised"
    assert "sql.destructive_ddl" in {r["rule_id"] for r in result.rules_fired}


def test_a_bounded_statement_through_the_same_tool_is_allowed(seeded, enforcer, db_agent):
    result = enforcer.guard_tool_call(
        agent_slug="support-triage",
        tool_key="db.query",
        arguments={"query": "SELECT name FROM users WHERE id = 1"},
    )
    assert not result.blocked
    assert result.taint["action"]["operation"] == "read"


def test_a_wildcard_value_in_an_ordinary_argument_is_blocked_through_a_granted_tool(seeded):
    """The over-privilege shape: `crm.lookup` is a plain, granted, read-only
    capability — nothing about the tool itself is dangerous. The danger is a
    benign-sounding request translated into `order_id="*"`, a field no SQL/shell/
    URL key-name dispatch would ever inspect."""
    from agentfox.runtime.enforcement import Enforcer

    agent = seeded.query(Agent).filter_by(slug="support-triage").one()
    identity = ensure_identity(seeded, agent)
    grant_capability(seeded, identity, "crm.lookup", max_taint="user")
    result = Enforcer(seeded).guard_tool_call(
        agent_slug="support-triage",
        tool_key="crm.lookup",
        arguments={"order_id": "*"},
    )
    assert result.blocked
    assert result.taint["capability"]["granted"] is True, "the tool itself was authorised"
    assert "scope.wildcard_value" in {r["rule_id"] for r in result.rules_fired}


def test_an_ordinary_lookup_by_id_through_the_same_tool_is_allowed(seeded):
    from agentfox.runtime.enforcement import Enforcer

    agent = seeded.query(Agent).filter_by(slug="support-triage").one()
    identity = ensure_identity(seeded, agent)
    grant_capability(seeded, identity, "crm.lookup", max_taint="user")
    result = Enforcer(seeded).guard_tool_call(
        agent_slug="support-triage",
        tool_key="crm.lookup",
        arguments={"order_id": "12345"},
    )
    assert not result.blocked


def test_the_action_summary_is_recorded_on_the_decision(seeded, enforcer, db_agent):
    result = enforcer.guard_tool_call(
        agent_slug="support-triage",
        tool_key="db.query",
        arguments={"query": "DELETE FROM users"},
    )
    action = result.taint["action"]
    assert action["blast_radius"] == "unbounded"
    assert action["targets"] == ["users"]
    assert action["parsed"] is True


def test_the_block_explains_itself(seeded, enforcer, db_agent):
    result = enforcer.guard_tool_call(
        agent_slug="support-triage",
        tool_key="db.query",
        arguments={"query": "DELETE FROM users"},
    )
    rule = next(r for r in result.rules_fired if r["rule_id"] == "sql.unbounded_mutation")
    assert "every row" in rule["reason"]
    assert rule["evidence"]["statement"]


# ---------------------------------------------------------------------------
# P9-7 verified state, P9-10 dry run
# ---------------------------------------------------------------------------


@pytest.fixture
def verified_agent(seeded):
    agent = seeded.query(Agent).filter_by(slug="support-triage").one()
    identity = ensure_identity(seeded, agent)
    grant_capability(
        seeded,
        identity,
        "hr.terminate",
        constraints={"requires_verified_state": True},
        max_taint="user",
    )
    return agent


def test_an_irreversible_act_without_a_state_read_is_blocked(seeded, enforcer, verified_agent):
    """The HR-termination failure: the agent acted on a stale or hallucinated view of
    the record."""
    result = enforcer.guard_tool_call(
        agent_slug="support-triage",
        tool_key="hr.terminate",
        arguments={"employee_id": "e-1"},
    )
    assert result.blocked
    assert result.rules_fired[-1]["rule_id"] == "action.unverified_state"


def test_a_fresh_state_read_authorises_it(seeded, enforcer, verified_agent):
    result = enforcer.guard_tool_call(
        agent_slug="support-triage",
        tool_key="hr.terminate",
        arguments={"employee_id": "e-1"},
        verified_state={"read_at": dt.datetime.now(dt.UTC).isoformat(), "source": "workday"},
    )
    assert "action.unverified_state" not in {r["rule_id"] for r in result.rules_fired}


def test_a_stale_state_read_is_refused(seeded, enforcer, verified_agent):
    stale = dt.datetime.now(dt.UTC) - dt.timedelta(hours=2)
    result = enforcer.guard_tool_call(
        agent_slug="support-triage",
        tool_key="hr.terminate",
        arguments={"employee_id": "e-1"},
        verified_state={"read_at": stale.isoformat()},
    )
    assert result.blocked
    assert "old" in result.rules_fired[-1]["reason"]


def test_the_reserved_constraint_is_not_treated_as_an_argument_path(
    seeded, enforcer, verified_agent
):
    """Reading `requires_verified_state` as a path would look for an argument by that
    name and fail every call for the wrong reason."""
    result = enforcer.guard_tool_call(
        agent_slug="support-triage",
        tool_key="hr.terminate",
        arguments={"employee_id": "e-1"},
        verified_state={"read_at": dt.datetime.now(dt.UTC).isoformat()},
    )
    assert result.taint["capability"]["constraint_violations"] == []


def test_a_dry_run_computes_the_verdict_without_refusing(seeded, enforcer, db_agent):
    """A dry run is analysis without execution — what makes a policy safe to roll out."""
    result = enforcer.guard_tool_call(
        agent_slug="support-triage",
        tool_key="db.query",
        arguments={"query": "DROP TABLE users"},
        dry_run=True,
    )
    assert result.verdict == "allow"
    assert result.taint["dry_run"] is True
    assert "sql.destructive_ddl" in {r["rule_id"] for r in result.rules_fired}
    assert result.effective_verdict == "block", "the counterfactual is still recorded"


# ---------------------------------------------------------------------------
# Nested arguments (found by the adaptive red-team engine, 2026-09-16)
# ---------------------------------------------------------------------------
#
# Taint tracking always flattened nested arguments, so a value at `params.sql` carried
# its provenance correctly — but action assurance only ever read the top level. Re-nesting
# the identical payload flipped a verdict from block to allow, which is the whole claim
# this module exists to make.


def test_a_destructive_statement_nested_one_level_is_still_analysed():
    from agentfox.detection.actions import analyse_arguments

    flat = analyse_arguments({"sql": "DELETE FROM customers"})
    nested = analyse_arguments({"params": {"sql": "DELETE FROM customers"}})
    assert len(nested) == len(flat) == 1
    assert nested[0].operation == flat[0].operation
    assert {r.code for r in nested[0].risks} == {r.code for r in flat[0].risks}


def test_a_destructive_statement_inside_a_list_is_analysed():
    from agentfox.detection.actions import analyse_arguments

    analyses = analyse_arguments({"batch": [{"query": "DELETE FROM orders"}]})
    assert analyses and "sql.unbounded_mutation" in {r.code for r in analyses[0].risks}


def test_a_wildcard_scope_value_nested_in_an_object_is_caught():
    from agentfox.detection.actions import analyse_arguments

    analyses = analyse_arguments({"filter": {"order_id": "*"}})
    assert analyses and "scope.wildcard_value" in {r.code for r in analyses[0].risks}


def test_the_sql_finder_walks_nested_arguments_too():
    """P18's access analysis shares this finder; the two must not drift."""
    from agentfox.detection.actions import find_sql_argument

    assert find_sql_argument({"params": {"query": "DROP TABLE x"}}) == "DROP TABLE x"


def test_ordinary_nested_arguments_stay_silent():
    from agentfox.detection.actions import analyse_arguments

    assert analyse_arguments({"customer": {"name": "Ada", "city": "Cambridge"}}) == []


def test_the_walk_is_bounded_in_depth_and_width():
    """A tool call is not a document: an unbounded walk is a latency problem."""
    from agentfox.detection.actions import analyse_arguments

    deep: dict = {"sql": "DELETE FROM customers"}
    for _ in range(12):
        deep = {"wrap": deep}
    assert analyse_arguments(deep) == []

    wide = {f"k{i}": "*" for i in range(600)}
    assert len(analyse_arguments(wide)) <= 256
