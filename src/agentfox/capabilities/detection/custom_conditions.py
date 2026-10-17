"""Value conditions: "when a refund's amount is more than 500", "only these regions".

Words, patterns and topics ask what a text *says*. A condition asks what a value
*is*: a field of a tool call's arguments or of its result, the length of a reply,
the first number in it. It is the general form of a business limit — the approval
ladders in ``capabilities/business`` are tool-argument thresholds with tiers, and a
condition is one comparison on any surface with the ordinary rule effects.

Pure, like the rest of the custom-rule matching: :class:`ConditionSpec` validates
what was authored, :func:`evaluate` reads one piece of content and returns the
values that satisfy it. The ``custom.lists`` detector turns a hit into a
``CUSTOM.<KEY>`` detection, so the rule ``custom.<key>`` decides, and a span lets
Mask rewrite a matched value in a reply.
"""

from __future__ import annotations

import fnmatch
import json
import re
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

CONDITION_SURFACES = ("tool_args", "tool_result", "output", "input")
TOOL_SURFACES = ("tool_args", "tool_result")

NUMERIC_OPERATORS = ("gt", "gte", "lt", "lte")
LIST_OPERATORS = ("in", "not_in")
TEXT_OPERATORS = ("contains", "not_contains")
PRESENCE_OPERATORS = ("exists", "missing")
OPERATORS = (
    *NUMERIC_OPERATORS,
    "eq",
    "ne",
    *LIST_OPERATORS,
    *TEXT_OPERATORS,
    "matches",
    *PRESENCE_OPERATORS,
)
#: What is compared: the value itself, its length, or the first number in it.
MEASURES = ("value", "length", "number")

MAX_VALUES = 500
_FIELD = re.compile(r"^[A-Za-z0-9_\-*$@]+(\.[A-Za-z0-9_\-*$@]+)*$")
_NUMBER = re.compile(r"-?\d[\d,]*(?:\.\d+)?|-?\.\d+")
_CURRENCY = re.compile(r"^[\s$€£¥₹]+|[\s]+$")


def as_number(value: Any) -> float | None:
    """A number, or None. Accepts "1,200.50" and "$500"; never a bool."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        text = _CURRENCY.sub("", value).replace(",", "")
        try:
            return float(text)
        except ValueError:
            return None
    return None


class ConditionSpec(BaseModel):
    """One comparison. ``field`` is a dot path into the JSON tool arguments or result
    (``refund.total``, ``items.0.price``, ``items.*.price``); empty means the whole
    text. ``value`` is a number, a string, or a list for ``in`` / ``not_in``."""

    surface: str = "tool_args"
    tool: str | None = Field(None, max_length=160)
    field: str = Field("", max_length=160)
    measure: str = "value"
    operator: str
    value: float | int | str | list[float | int | str] | None = None
    case_sensitive: bool = False

    @field_validator("surface")
    @classmethod
    def _surface(cls, v: str) -> str:
        if v not in CONDITION_SURFACES:
            raise ValueError(
                f"unknown place to check '{v}': use one of {', '.join(CONDITION_SURFACES)}"
            )
        return v

    @field_validator("operator")
    @classmethod
    def _operator(cls, v: str) -> str:
        v = (v or "").strip().lower()
        if v not in OPERATORS:
            raise ValueError(f"unknown operator '{v}': use one of {', '.join(OPERATORS)}")
        return v

    @field_validator("measure")
    @classmethod
    def _measure(cls, v: str) -> str:
        if v not in MEASURES:
            raise ValueError(f"unknown measure '{v}': use one of {', '.join(MEASURES)}")
        return v

    @field_validator("field")
    @classmethod
    def _field(cls, v: str) -> str:
        v = (v or "").strip().removeprefix("arguments.").removeprefix("result.")
        if v and not _FIELD.match(v):
            raise ValueError(f"field '{v}' should be a dot path such as amount or refund.total")
        return v

    @field_validator("tool")
    @classmethod
    def _tool(cls, v: str | None) -> str | None:
        return (v or "").strip() or None

    @model_validator(mode="after")
    def _shape(self) -> ConditionSpec:
        if self.surface not in TOOL_SURFACES:
            self.tool = None
        op = self.operator
        if self.measure != "value" and op not in (*NUMERIC_OPERATORS, "eq", "ne"):
            raise ValueError(f"a {self.measure} can only be compared as a number")
        if op in PRESENCE_OPERATORS:
            if not self.field:
                raise ValueError(f"'{op}' needs a field to look for")
            self.value = None
            return self
        if op in NUMERIC_OPERATORS or self.measure != "value":
            if isinstance(self.value, list):
                raise ValueError(f"'{op}' compares against one number, not a list")
            number = as_number(self.value)
            if number is None:
                raise ValueError(f"'{op}' needs a number, got {self.value!r}")
            self.value = int(number) if number.is_integer() else number
            return self
        if op in LIST_OPERATORS:
            items = self.value if isinstance(self.value, list) else str(self.value or "").split(",")
            cleaned = list(
                dict.fromkeys(
                    i.strip() if isinstance(i, str) else i
                    for i in items
                    if i is not None and str(i).strip()
                )
            )
            if not cleaned:
                raise ValueError(f"'{op}' needs at least one value")
            if len(cleaned) > MAX_VALUES:
                raise ValueError(f"at most {MAX_VALUES} values")
            self.value = cleaned
            return self
        if isinstance(self.value, list):
            raise ValueError(f"'{op}' compares against one value, not a list")
        if self.value is None or str(self.value).strip() == "":
            raise ValueError(f"'{op}' needs a value")
        if op == "matches":
            from agentfox.capabilities.detection.custom import validate_pattern

            self.value = validate_pattern(str(self.value))
        return self


@dataclass(frozen=True)
class Hit:
    """A value that satisfied the condition, and where it sits in the content if known."""

    observed: Any
    start: int
    end: int


def applies_to_tool(cond: ConditionSpec, tool_key: str | None) -> bool:
    """A tool glob only matches a known tool; without one the condition covers every tool."""
    if not cond.tool or cond.surface not in TOOL_SURFACES:
        return True
    return tool_key is not None and fnmatch.fnmatch(tool_key.lower(), cond.tool.lower())


def evaluate(cond: ConditionSpec, content: str, tool_key: str | None = None) -> list[Hit]:
    """Every value in ``content`` that satisfies ``cond``; empty when it does not fire."""
    if not applies_to_tool(cond, tool_key):
        return []
    whole = (content or "", 0, len(content or ""))
    if cond.field:
        data = _parse(content)
        found = [] if data is _MISSING else _resolve(data, cond.field.split("."))
        located = [(v, *_locate(content, v)) for v in found]
    else:
        located = [whole] if content else []

    if cond.operator == "exists":
        return [Hit(v, s, e) for v, s, e in located if v is not None][:1]
    if cond.operator == "missing":
        return [] if any(v is not None for v, _, _ in located) else [Hit(None, 0, 0)]

    hits: list[Hit] = []
    for value, start, end in located:
        for observed, s, e in _measured(cond, value, start, end, from_text=not cond.field):
            span = _span_in(cond, observed, s, e)
            if span is not None:
                hits.append(Hit(observed, *span))
    return hits


def observed_values(cond: ConditionSpec, content: str, limit: int = 5) -> list[Any]:
    """What the condition reads from ``content`` before comparing, for a tester to show
    a near miss ("amount is 450") apart from a field that is not there at all."""
    if cond.field:
        data = _parse(content)
        found = [] if data is _MISSING else _resolve(data, cond.field.split("."))
    else:
        found = [content] if content else []
    if cond.operator in PRESENCE_OPERATORS:
        return found[:limit]
    out: list[Any] = []
    for value in found:
        out.extend(v for v, _, _ in _measured(cond, value, 0, 0, from_text=False))
    return out[:limit]


# --- reading values -------------------------------------------------------------

_MISSING = object()


def _parse(content: str) -> Any:
    try:
        return json.loads(content)
    except (TypeError, ValueError):
        return _MISSING


def _resolve(data: Any, parts: list[str]) -> list[Any]:
    """The values at a dot path; ``*`` fans out over a list or an object."""
    if not parts:
        return [data]
    head, rest = parts[0], parts[1:]
    if head == "*":
        children = (
            data
            if isinstance(data, list)
            else list(data.values())
            if isinstance(data, dict)
            else []
        )
        return [v for child in children for v in _resolve(child, rest)]
    if isinstance(data, dict):
        return _resolve(data[head], rest) if head in data else []
    if isinstance(data, list) and re.fullmatch(r"-?\d+", head):
        idx = int(head)
        return _resolve(data[idx], rest) if -len(data) <= idx < len(data) else []
    return []


def _locate(content: str, value: Any) -> tuple[int, int]:
    """Where a JSON value appears in the raw content; the whole content if unsure."""
    if isinstance(value, str | int | float) and not isinstance(value, bool):
        needle = json.dumps(value) if isinstance(value, str) else str(value)
        at = content.find(needle)
        if at >= 0:
            if isinstance(value, str):  # inside the quotes
                return at + 1, at + len(needle) - 1
            return at, at + len(needle)
    return 0, len(content)


def _measured(cond: ConditionSpec, value: Any, start: int, end: int, *, from_text: bool):
    """What is compared: the value (a list's items, one by one), its length, or the
    first number in it."""
    if cond.measure == "length":
        if value is None:
            return []
        size = len(value) if isinstance(value, str | list | dict) else len(str(value))
        return [(size, start, end)]
    if cond.measure == "number":
        if isinstance(value, int | float) and not isinstance(value, bool):
            return [(value, start, end)]
        m = _NUMBER.search(value if isinstance(value, str) else "")
        if not m:
            return []
        number = as_number(m.group(0))
        if number is None:
            return []
        if from_text or end - start == len(value):
            return [(number, start + m.start(), start + m.end())]
        return [(number, start, end)]
    if isinstance(value, list) and cond.operator not in TEXT_OPERATORS:
        return [(item, start, end) for item in value]
    return [(value, start, end)]


# --- comparing ------------------------------------------------------------------


def _text(value: Any, case_sensitive: bool) -> str:
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    return text if case_sensitive else text.casefold()


def _equal(a: Any, b: Any, case_sensitive: bool) -> bool:
    na, nb = as_number(a), as_number(b)
    if na is not None and nb is not None:
        return na == nb
    return _text(a, case_sensitive).strip() == _text(b, case_sensitive).strip()


def _span_in(cond: ConditionSpec, observed: Any, start: int, end: int) -> tuple[int, int] | None:
    """The span to report when ``observed`` satisfies the condition, else None."""
    op, expected, cs = cond.operator, cond.value, cond.case_sensitive
    if observed is None:
        return None
    if op in NUMERIC_OPERATORS:
        n, limit = as_number(observed), float(expected)  # type: ignore[arg-type]
        if n is None:
            return None
        ok = {"gt": n > limit, "gte": n >= limit, "lt": n < limit, "lte": n <= limit}[op]
        return (start, end) if ok else None
    if op == "eq":
        return (start, end) if _equal(observed, expected, cs) else None
    if op == "ne":
        return None if _equal(observed, expected, cs) else (start, end)
    if op in LIST_OPERATORS:
        inside = any(_equal(observed, item, cs) for item in expected)  # type: ignore[union-attr]
        return (start, end) if inside == (op == "in") else None
    if op in TEXT_OPERATORS:
        items = observed if isinstance(observed, list) else [observed]
        needle = _text(str(expected), cs)
        found = any(needle in _text(i, cs) for i in items)
        if op == "not_contains":
            return None if found else (start, end)
        if not found:
            return None
        if isinstance(observed, str):
            at = _text(observed, cs).find(needle)
            if at >= 0 and end - start == len(observed):
                return start + at, start + at + len(needle)
        return start, end
    if op == "matches":
        text = observed if isinstance(observed, str) else json.dumps(observed, default=str)
        m = re.search(str(expected), text, 0 if cs else re.IGNORECASE)
        if m is None:
            return None
        if end - start == len(text):
            return start + m.start(), start + m.end()
        return start, end
    return None
