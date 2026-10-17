"""Rule tables: rules translated from another policy language, run as one pack check.

Several packs carry rules translated from Rego policies written against a simple
input: an ``action`` (the tool name), its ``params`` (the tool arguments), the
``output`` text, and a free-form ``context``. Most of those rules test things the
declarative policy format cannot test directly (a regular expression over the text,
a tool argument that is *missing*, a set of tool names), so a pack ships them as a
table and one check evaluates the table, emitting a risk code per rule that matched.
The pack's policy then turns each code into an effect with ``action_risk``, so the
verdict, the mode and the audit trail are the policy engine's as usual.

The input a rule sees on each surface is the one the source policies saw:

* ``tool_args``: ``action`` is the tool key, ``params`` its arguments, ``output`` "";
* ``input`` and ``output``: ``action`` is the surface name, ``params`` is empty, and
  ``output`` is the message text (or, for a table marked ``args_as_text``, also the
  tool arguments on ``tool_args``, rendered as JSON);
* ``context`` is ``evidence["context"]`` when the caller supplies one, else ``{}``.

Comparisons follow Rego: a test on a value that is absent is false (and its ``not``
form true), equality is typed (``true`` is not ``1``), and ordering across types
uses Rego's order (null < boolean < number < string < array < object). Regular
expressions run with Python's ``re`` in ASCII mode, the closest match to RE2's
``\\b``, ``\\d`` and ``\\w``; the source patterns use nothing RE2 lacks.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from functools import cache
from typing import Any

#: Severity of the risk a rule raises, by the source rule's outcome. Never
#: ``critical``: critical action risks are hard-blocked by the runtime whatever the
#: pack's mode, and these packs must start in observe.
SEVERITY = {"deny": "high", "escalate": "medium", "audit": "low"}

_ABSENT = object()


@dataclass(frozen=True)
class TableRule:
    """One translated rule: every condition must hold (AND)."""

    code: str
    outcome: str  # deny | escalate | audit
    reason: str
    #: Conditions, each a tuple whose first item names its kind:
    #: ("text", regex) — the regex is found in ``output``;
    #: ("action_in", names); ("action_re", regex) — found in ``action``;
    #: ("action_has", substrings) — ``action`` contains any of them;
    #: ("param", key, op, value), op one of == != > >= < <= in — false when the
    #:   key is absent; ("param_set", key) — present and not false;
    #: ("ctx", …) and ("ctx_set", key) — the same against ``context``;
    #: ("ctx_get", key, default, op, value) — ``object.get(context, key, default)``;
    #: ("param_num", key, op, value, default) — the param if it is a number,
    #:   else ``default``; ("ctx_nonempty_str", key); ("ctx_ne_ctx", a, b);
    #: ("params_text_contains", fields, needles) — a lower-cased string param
    #:   named in ``fields`` contains one of ``needles``.
    #: Any kind prefixed ``not_`` is its negation, as Rego's ``not``: true when the
    #: test fails *or* the value is absent.
    when: tuple[tuple[Any, ...], ...] = field(default_factory=tuple)


def _type_rank(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, bool):
        return 1
    if isinstance(value, int | float):
        return 2
    if isinstance(value, str):
        return 3
    if isinstance(value, list | tuple):
        return 4
    if isinstance(value, Mapping):
        return 5
    return 6


def _eq(a: Any, b: Any) -> bool:
    return _type_rank(a) == _type_rank(b) and a == b


def _compare(a: Any, op: str, b: Any) -> bool:
    if op == "==":
        return _eq(a, b)
    if op == "!=":
        return not _eq(a, b)
    if op == "in":
        return any(_eq(a, item) for item in b)
    ra, rb = _type_rank(a), _type_rank(b)
    if ra != rb:
        left, right = ra, rb
    else:
        try:
            left, right = a, b
            _ = left < right
        except TypeError:
            return False
    return {
        ">": left > right,
        ">=": left >= right,
        "<": left < right,
        "<=": left <= right,
    }[op]


@cache
def _regex(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.ASCII)


def _truthy(value: Any) -> bool:
    """A bare Rego reference holds when it is defined and not ``false``."""
    return value is not _ABSENT and value is not False


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _base(cond: tuple[Any, ...], action: str, params: Mapping, text: str, ctx: Mapping) -> bool:
    kind = cond[0]
    if kind == "text":
        return isinstance(text, str) and _regex(cond[1]).search(text) is not None
    if kind == "action_in":
        return action in cond[1]
    if kind == "action_re":
        return _regex(cond[1]).search(action) is not None
    if kind == "action_has":
        return any(part in action for part in cond[1])
    if kind == "ctx_get":
        _, key, default, op, value = cond
        return _compare(ctx.get(key, default), op, value)
    if kind == "param_num":
        # `x := input.params.k if is_number(input.params.k) else := default`
        _, key, op, value, default = cond
        actual = params.get(key)
        return _compare(actual if _is_number(actual) else default, op, value)
    if kind == "ctx_nonempty_str":
        value = ctx.get(cond[1])
        return isinstance(value, str) and value != ""
    if kind == "ctx_ne_ctx":
        a, b = ctx.get(cond[1], _ABSENT), ctx.get(cond[2], _ABSENT)
        return a is not _ABSENT and b is not _ABSENT and not _eq(a, b)
    if kind == "params_text_contains":
        # Any string param named in cond[1], lower-cased, contains any of cond[2].
        texts = [params[f].lower() for f in cond[1] if isinstance(params.get(f), str)]
        return any(needle in t for t in texts for needle in cond[2])
    source = ctx if kind.startswith("ctx") else params
    if kind in ("param_set", "ctx_set"):
        return _truthy(source.get(cond[1], _ABSENT))
    if kind in ("param", "ctx"):
        _, key, op, value = cond
        actual = source.get(key, _ABSENT)
        return actual is not _ABSENT and _compare(actual, op, value)
    raise ValueError(f"unknown rule-table condition {kind!r}")


def _holds(cond: tuple[Any, ...], action: str, params: Mapping, text: str, ctx: Mapping) -> bool:
    """One condition; a ``not_`` prefix on any kind negates it (Rego ``not``)."""
    kind = cond[0]
    if kind.startswith("not_"):
        return not _base((kind[4:], *cond[1:]), action, params, text, ctx)
    return _base(cond, action, params, text, ctx)


def evaluate(
    rules: Iterable[TableRule],
    *,
    surface: str,
    content: str | None,
    tool_key: str | None,
    arguments: Mapping[str, Any] | None,
    evidence: Mapping[str, Any] | None = None,
    args_as_text: bool = False,
) -> list[TableRule]:
    """The rules that match one call, in table order."""
    context = (evidence or {}).get("context") or {}
    if surface == "tool_args":
        params = dict(arguments or {})
        text = json.dumps(params, sort_keys=True, default=str) if args_as_text else ""
        return match(rules, action=str(tool_key or ""), params=params, text=text, context=context)
    if surface in ("input", "output"):
        return match(rules, action=surface, params={}, text=content or "", context=context)
    return []


def match(
    rules: Iterable[TableRule],
    *,
    action: str,
    params: Mapping[str, Any],
    text: Any,
    context: Any,
) -> list[TableRule]:
    """The rules that match the source policies' own input shape, in table order."""
    ctx = context if isinstance(context, Mapping) else {}
    params = params if isinstance(params, Mapping) else {}
    text = text if isinstance(text, str) else ""
    return [rule for rule in rules if all(_holds(c, action, params, text, ctx) for c in rule.when)]


def decision(matched: Iterable[TableRule]) -> str:
    """The source policies' decision for these matches: deny > escalate > audit > allow."""
    outcomes = {rule.outcome for rule in matched}
    return next((o for o in ("deny", "escalate", "audit") if o in outcomes), "allow")


def as_risks(matched: Iterable[TableRule]) -> dict[str, Any]:
    """A content check's result for these matches: one risk per rule."""
    risks = [
        {"code": rule.code, "severity": SEVERITY[rule.outcome], "detail": rule.reason}
        for rule in matched
    ]
    return {"risks": risks} if risks else {}


def run(rules: Iterable[TableRule], ctx: Any, *, args_as_text: bool = False) -> dict[str, Any]:
    """Evaluate a table against a `CheckContext` and return the check result."""
    return as_risks(
        evaluate(
            rules,
            surface=ctx.surface,
            content=ctx.content,
            tool_key=ctx.tool_key,
            arguments=ctx.arguments,
            evidence=ctx.evidence,
            args_as_text=args_as_text,
        )
    )


__all__ = ["SEVERITY", "TableRule", "as_risks", "decision", "evaluate", "match", "run"]
