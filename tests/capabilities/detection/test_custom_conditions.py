"""Value conditions: what they accept, and what each operator family fires on."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from agentfox.capabilities.detection.base import DetectionContext
from agentfox.capabilities.detection.custom import CustomListDetector, CustomRuleSpec, compile_rule
from agentfox.capabilities.detection.custom_conditions import (
    ConditionSpec,
    evaluate,
    observed_values,
)


def _fires(cond: dict, content, tool: str | None = None) -> bool:
    text = content if isinstance(content, str) else json.dumps(content)
    return bool(evaluate(ConditionSpec(**cond), text, tool))


def _detect(cond: dict, content, surface="tool_args", tool=None):
    rule = compile_rule(CustomRuleSpec(key="limit", name="Limit", kind="condition", condition=cond))
    text = content if isinstance(content, str) else json.dumps(content)
    return (
        CustomListDetector()
        .detect(
            text, DetectionContext(surface=surface, tool_key=tool, extra={"custom_rules": [rule]})
        )
        .detections
    )


# --- validation -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("cond", "message"),
    [
        ({"field": "amount", "operator": "bigger", "value": 1}, "unknown operator"),
        ({"field": "amount", "operator": "gt", "value": "lots"}, "needs a number"),
        ({"field": "amount", "operator": "gt", "value": [1, 2]}, "one number"),
        ({"field": "x", "operator": "matches", "value": "(a+)+$"}, "repeat inside a repeat"),
        ({"field": "x", "operator": "matches", "value": "("}, "not a valid regular expression"),
        ({"field": "x", "operator": "matches", "value": "a" * 400}, "longer than"),
        ({"field": "x", "operator": "in", "value": []}, "at least one value"),
        ({"field": "", "operator": "exists"}, "needs a field"),
        ({"field": "x", "operator": "contains", "value": ""}, "needs a value"),
        ({"surface": "memory", "field": "x", "operator": "eq", "value": 1}, "unknown place"),
        ({"field": "x y", "operator": "eq", "value": 1}, "dot path"),
        (
            {"surface": "output", "measure": "length", "operator": "contains", "value": 3},
            "compared as a number",
        ),
    ],
)
def test_bad_conditions_are_refused_in_plain_words(cond, message):
    with pytest.raises(ValidationError) as err:
        ConditionSpec(**cond)
    assert message in str(err.value)


def test_values_are_normalised():
    assert ConditionSpec(field="amount", operator="GT", value="1,500").value == 1500
    assert ConditionSpec(field="region", operator="not_in", value="eu, us ,eu").value == [
        "eu",
        "us",
    ]
    assert ConditionSpec(surface="output", field="x", operator="eq", value=1, tool="t").tool is None
    assert ConditionSpec(field="arguments.amount", operator="gt", value=1).field == "amount"


def test_a_condition_rule_checks_only_its_own_surface():
    spec = CustomRuleSpec(
        key="big",
        name="Big",
        kind="condition",
        condition={"surface": "tool_result", "field": "total", "operator": "gt", "value": 5},
        surfaces=["input", "output"],
    )
    assert spec.surfaces == ["tool_result"]
    with pytest.raises(ValidationError):
        CustomRuleSpec(key="big", name="Big", kind="condition")


# --- operator families --------------------------------------------------------------


def test_numeric_comparisons_on_a_field():
    args = {"amount": 750, "refund": {"total": "1,200.00"}}
    assert _fires({"field": "amount", "operator": "gt", "value": 500}, args)
    assert not _fires({"field": "amount", "operator": "gt", "value": 750}, args)
    assert _fires({"field": "amount", "operator": "gte", "value": 750}, args)
    assert _fires({"field": "refund.total", "operator": "gt", "value": 1000}, args)
    assert _fires({"field": "amount", "operator": "lt", "value": 1000}, args)
    assert not _fires({"field": "amount", "operator": "lte", "value": 100}, args)
    # A missing or non-numeric value never satisfies a comparison.
    assert not _fires({"field": "fee", "operator": "gt", "value": 0}, args)
    assert not _fires({"field": "amount", "operator": "gt", "value": 0}, {"amount": "n/a"})


def test_lists_by_index_and_by_wildcard():
    order = {"items": [{"price": 20}, {"price": 900}]}
    assert not _fires({"field": "items.0.price", "operator": "gt", "value": 100}, order)
    assert _fires({"field": "items.1.price", "operator": "gt", "value": 100}, order)
    assert _fires({"field": "items.*.price", "operator": "gt", "value": 100}, order)


def test_equality_and_allowed_values():
    args = {"currency": "USD", "region": "apac", "tags": ["vip", "beta"]}
    assert _fires({"field": "currency", "operator": "eq", "value": "usd"}, args)
    assert not _fires(
        {"field": "currency", "operator": "eq", "value": "usd", "case_sensitive": True}, args
    )
    assert _fires({"field": "currency", "operator": "ne", "value": "EUR"}, args)
    # "Only these values are allowed" is not_in: anything else fires.
    allowed = {"field": "region", "operator": "not_in", "value": ["us", "eu"]}
    assert _fires(allowed, args) and not _fires(allowed, {"region": "EU"})
    assert _fires({"field": "region", "operator": "in", "value": "apac, latam"}, args)
    # Each item of a list is checked.
    assert _fires({"field": "tags", "operator": "not_in", "value": ["vip"]}, args)
    assert not _fires({"field": "tags", "operator": "not_in", "value": ["vip", "beta"]}, args)
    assert _fires({"field": "n", "operator": "eq", "value": 2}, {"n": "2.0"})


def test_text_operators():
    args = {"to": "someone@gmail.com", "body": "see attached"}
    assert _fires({"field": "to", "operator": "contains", "value": "@gmail"}, args)
    assert _fires({"field": "to", "operator": "not_contains", "value": "@acme.com"}, args)
    assert not _fires({"field": "to", "operator": "not_contains", "value": "gmail"}, args)
    assert _fires({"field": "to", "operator": "matches", "value": r"@(gmail|yahoo)\."}, args)
    assert not _fires({"field": "to", "operator": "matches", "value": r"@acme\.com$"}, args)


def test_presence():
    assert _fires({"field": "cc", "operator": "exists"}, {"cc": "x@y.z"})
    assert not _fires({"field": "cc", "operator": "exists"}, {"to": "x"})
    assert _fires({"field": "approval_id", "operator": "missing"}, {"to": "x"})
    assert not _fires({"field": "approval_id", "operator": "missing"}, {"approval_id": "a1"})


def test_whole_text_length_and_first_number():
    long_reply = {"surface": "output", "measure": "length", "operator": "gt", "value": 20}
    assert _fires(long_reply, "This reply is definitely longer than twenty characters.")
    assert not _fires(long_reply, "Short.")
    first_number = {"surface": "output", "measure": "number", "operator": "gt", "value": 500}
    assert _fires(first_number, "We can refund $1,250.00 today.")
    assert not _fires(first_number, "We can refund $50 today, or 900 points.")
    assert not _fires(first_number, "No numbers here.")


def test_a_tool_glob_limits_the_condition():
    cond = {"tool": "payments.*", "field": "amount", "operator": "gt", "value": 10}
    assert _fires(cond, {"amount": 50}, tool="payments.refund")
    assert not _fires(cond, {"amount": 50}, tool="crm.update")
    assert not _fires(cond, {"amount": 50}, tool=None)


def test_detections_carry_the_rule_entity_and_a_span():
    text = json.dumps({"id": "a", "amount": 750})
    [d] = _detect({"field": "amount", "operator": "gt", "value": 500}, text)
    assert d.entity_type == "CUSTOM.LIMIT" and d.detail["kind"] == "condition"
    assert text[d.start : d.end] == "750"
    reply = "Refund of 1250 approved."
    [m] = _detect(
        {"surface": "output", "measure": "number", "operator": "gt", "value": 500},
        reply,
        surface="output",
    )
    assert reply[m.start : m.end] == "1250"
    # A tool-call condition does not look at replies.
    assert not _detect({"field": "amount", "operator": "gt", "value": 500}, text, "output")


def test_observed_values_show_a_near_miss():
    cond = ConditionSpec(field="amount", operator="gt", value=500)
    assert observed_values(cond, json.dumps({"amount": 450})) == [450]
    assert observed_values(cond, json.dumps({"x": 1})) == []
