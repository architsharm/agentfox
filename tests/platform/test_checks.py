"""The check registry: what the Enforcer runs, in what order, and how results merge."""

from __future__ import annotations

import pytest

from agentfox.platform import checks as registry
from agentfox.runtime.checks import BUILTIN_CHECK_MODULES, checks_for
from agentfox.runtime.enforcement import Enforcer

#: The order `Enforcer._run_content_checks` called these in before they were
#: registered: evidence and disclosure, then commitment, context, control flow,
#: sycophancy and trajectory. A change here changes what decisions record.
LEGACY_ORDER = [
    "grounding.evidence",
    "grounding.disclosure",
    "grounding.commitments",
    "grounding.context",
    "containment.control_flow",
    "grounding.sycophancy",
    "detection.trajectory",
]


def builtin(kind="content", surface=None):
    registry.load(BUILTIN_CHECK_MODULES)
    return [c.key for c in registry.checks(kind, surface) if c.source == "builtin"]


def test_the_builtin_content_checks_run_in_the_order_they_always_have():
    assert builtin() == LEGACY_ORDER


@pytest.mark.parametrize(
    ("surface", "expected"),
    [
        (
            "output",
            [
                "grounding.evidence",
                "grounding.disclosure",
                "grounding.commitments",
                "grounding.sycophancy",
            ],
        ),
        ("input", ["detection.trajectory"]),
        ("tool_args", ["containment.control_flow"]),
        ("retrieved", ["grounding.context"]),
        ("tool_result", ["grounding.context"]),
        ("memory_write", ["grounding.context"]),
        ("agent_message", []),
    ],
)
def test_each_check_runs_only_on_its_surfaces(surface, expected):
    assert builtin(surface=surface) == expected


def test_the_business_ladders_are_a_ladder_check_on_tool_arguments():
    assert builtin("ladder") == ["business.ladders"]
    assert builtin("ladder", "output") == []


def test_merge_keeps_an_explicit_empty_issue_list_and_concatenates_the_rest():
    evidence, risks = registry.merge_content(
        [
            {"provenance": 1, "evidence_issues": []},
            None,
            {},
            {"disclosure": 2, "evidence_issues": [{"type": "a"}]},
            {"commitments": 3, "evidence_issues": [{"type": "b"}], "risks": [{"code": "x"}]},
        ]
    )
    assert list(evidence) == ["provenance", "evidence_issues", "disclosure", "commitments"]
    assert evidence["evidence_issues"] == [{"type": "a"}, {"type": "b"}]
    assert risks == [{"code": "x"}]


@pytest.fixture
def custom_check():
    keys = []

    def add(key, fn, **kwargs):
        registry.register(registry.Check(key=key, fn=fn, source="pack:test", **kwargs))
        keys.append(key)

    yield add
    for key in keys:
        registry.unregister(key)


def test_a_registered_check_reaches_policy_through_action_risks(custom_check):
    seen = []

    def promise(ctx):
        seen.append((ctx.surface, ctx.content))
        return {
            "payments_promise": True,
            "evidence_issues": [{"type": "binding_commitment", "title": "t", "severity": "high"}],
            "risks": [{"code": "payments.promise", "severity": "high", "detail": "d"}],
        }

    custom_check("test.promise", promise, surfaces=frozenset({"output"}), order=5000)
    assert checks_for("output")[-1].key == "test.promise"

    from agentfox.core.db import session_scope

    with session_scope() as session:
        result = Enforcer(session).evaluate(
            agent=None, identity=None, content="refund sent", surface="output"
        )
    assert seen == [("output", "refund sent")]
    assert result.taint["payments_promise"] is True
    assert {"code": "payments.promise", "severity": "high", "detail": "d"} in result.taint[
        "action"
    ]["risks"]


def test_a_check_that_is_not_built_in_cannot_fail_the_request(custom_check):
    def broken(ctx):
        raise RuntimeError("boom")

    custom_check("test.broken", broken, order=1)

    from agentfox.core.db import session_scope

    with session_scope() as session:
        result = Enforcer(session).evaluate(
            agent=None, identity=None, content="hello", surface="input"
        )
    assert result.verdict == "allow"


def test_a_key_registered_twice_keeps_the_first(custom_check):
    custom_check("test.dup", lambda ctx: {"first": True})
    registry.register(registry.Check(key="test.dup", fn=lambda ctx: {}, source="pack:other"))
    (dup,) = [c for c in registry.checks() if c.key == "test.dup"]
    assert dup.source == "pack:test"


def test_the_check_decorator_records_where_a_check_came_from():
    def loader():
        @registry.check("test.decorated", surfaces=["input"], order=7)
        def decorated(ctx):
            """One line of description."""
            return {}

    try:
        registry.import_as("pack:demo", loader)
        (found,) = [c for c in registry.checks() if c.key == "test.decorated"]
        assert found.source == "pack:demo"
        assert found.description == "One line of description."
        assert found.to_json()["surfaces"] == ["input"]
    finally:
        registry.unregister("test.decorated")
