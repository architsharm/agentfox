"""Translate agent-governance policies into AgentFox `PolicyDocument`s.

Two input formats, both as published with the Agent Governance Toolkit:

* **Rule YAML** (``apiVersion: governance.toolkit/v1``): ``rules`` with a string
  ``condition``, an ``action`` and a ``priority``, plus a policy-wide
  ``default_action``. Their evaluator reads a condition with a handful of regular
  expressions; anything those do not recognise — including a comparison of two
  fields, ``user.role == resource.owner`` — falls through to "unrecognised", which
  matches every call for a deny rule and none for an allow rule. Here every
  condition is parsed properly and either translated or reported.
* **Policy manifests** (``agent_control_specification_version``): checked against
  the published JSON Schemas (`schema/`), then each Rego policy bound to an
  intervention point is read for its decision rules (`rego_subset.py`).

The rules this translation keeps:

1. **Never drop a rule silently.** Every rule in the input is an `Item`: translated,
   translated with a note, or not translatable with the reason.
2. **Never loosen.** A condition is translated only when the result fires at least
   whenever theirs would for the same call; a deny never becomes an allow. Their
   engine lets a higher-priority allow override a deny; ours takes the strongest
   effect, so an allow never overrides anything (stricter, and said so).
3. **Make an open default visible.** ``default_action: allow`` means a call no
   rule matches passes. It is reported on its own, not buried in a list.

Text conditions (a regular expression over a message or output) have no field in
`Condition`; they become a `TextPattern` — a custom pattern rule that reports a
``CUSTOM.<KEY>`` detection — and the policy rule tests for that detection. The
caller saves the patterns (`capabilities/detection/importers/agent_governance.py`).

Pure: no database, no network, never runs the input.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml

from agentfox.platform.policy.compat import rego_subset
from agentfox.platform.policy.compat.rego_subset import RegoModule, RegoRule
from agentfox.platform.policy.compat.schema_check import SchemaError, validate
from agentfox.platform.policy.model import (
    ArgumentCondition,
    Condition,
    DetectionCondition,
    PolicyDocument,
    Rule,
)

Status = Literal["translated", "translated_with_note", "untranslatable"]

#: Their lifecycle stage -> our surface.
STAGE_SURFACE = {
    "pre_input": "input",
    "pre_tool": "tool_args",
    "post_tool": "tool_result",
    "pre_output": "output",
}
#: Manifest intervention point -> our surface. Points with no equivalent are absent.
POINT_SURFACE = {
    "input": "input",
    "output": "output",
    "pre_tool_call": "tool_args",
    "post_tool_call": "tool_result",
}
TEXT_SURFACES = ("input", "output", "tool_args", "tool_result")

#: Their rule action -> our effect. `allow` is handled separately.
ACTION_EFFECT = {
    "deny": "block",
    "block": "block",
    "require_approval": "escalate",
    "escalate": "escalate",
    "warn": "allow",
    "log": "allow",
    "audit": "allow",
}
#: Rego decision sets, by name, -> the effect of a rule adding to them.
SET_EFFECT = {
    "deny": "block",
    "denials": "block",
    "denies": "block",
    "violation": "block",
    "violations": "block",
    "block": "block",
    "blocked": "block",
    "escalate": "escalate",
    "escalations": "escalate",
    "require_approval": "escalate",
    "approvals": "escalate",
    "audit": "allow",
    "audits": "allow",
    "warn": "allow",
    "warnings": "allow",
    "warning": "allow",
    "allow": "allow-exception",
    "allows": "allow-exception",
    "allowed": "allow-exception",
}
SEVERITY = {"block": "high", "escalate": "medium", "allow": "low"}

#: Context fields that name the tool being called.
TOOL_FIELDS = {
    "tool",
    "tool_name",
    "tool.name",
    "action.tool",
    "action.tool_name",
    "action.name",
    "function",
    "function_name",
    "tool_call.name",
}
AGENT_FIELDS = {"agent", "agent_id", "agent.id", "agent.name", "agent_did", "agent.did"}
TEXT_FIELDS = {
    "message",
    "content",
    "input",
    "prompt",
    "text",
    "output",
    "response",
    "query",
    "input.text",
    "input.body",
    "output.text",
    "output.content",
    "message.content",
}
PII_FIELDS = {"data.contains_pii", "contains_pii", "data.pii", "pii_detected"}
ARGUMENT_PREFIXES = (
    "args.",
    "arguments.",
    "params.",
    "parameters.",
    "tool_args.",
    "action.args.",
    "action.params.",
    "action.arguments.",
    "tool.args.",
    "tool_call.args.",
)

UNRECOGNISED = (
    "their evaluator does not recognise this syntax: there it matches every call for a "
    "deny rule and no call for an allow rule"
)


class Untranslatable(Exception):
    """A condition our model cannot express. The message is the reason shown."""


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


@dataclass
class TextPattern:
    """A regular expression over text, saved as a custom pattern rule."""

    key: str
    name: str
    pattern: str
    surfaces: list[str]
    case_sensitive: bool = True

    @property
    def entity(self) -> str:
        return f"CUSTOM.{self.key.upper().replace('-', '_')}"

    def to_json(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "name": self.name,
            "pattern": self.pattern,
            "surfaces": self.surfaces,
            "case_sensitive": self.case_sensitive,
            "entity": self.entity,
        }


@dataclass
class Item:
    """One rule from the input and what became of it."""

    source: str
    status: Status
    #: Their action or decision set (`deny`, `require_approval`, `escalations` …).
    source_effect: str = ""
    #: Ours, once translated.
    effect: str = ""
    document: str = ""
    rules: list[str] = field(default_factory=list)
    patterns: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    reason: str = ""
    condition: str = ""
    line: int | None = None
    file: str = ""
    #: False for a part of another rule (an exception to a default deny): it
    #: cannot be left out on its own.
    skippable: bool = True

    def to_json(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "status": self.status,
            "source_effect": self.source_effect,
            "effect": self.effect,
            "document": self.document,
            "rules": self.rules,
            "patterns": self.patterns,
            "notes": self.notes,
            "reason": self.reason,
            "condition": self.condition,
            "line": self.line,
            "file": self.file,
            "skippable": self.skippable,
        }


@dataclass
class DefaultAction:
    document: str
    #: What the source said: `allow`, `deny`, or `unknown` when it could not be read.
    source: str
    effect: str
    #: True when a call no rule matches passes.
    unmatched_pass: bool
    note: str

    def to_json(self) -> dict[str, Any]:
        return {
            "document": self.document,
            "source": self.source,
            "effect": self.effect,
            "unmatched_pass": self.unmatched_pass,
            "note": self.note,
        }


@dataclass
class Translation:
    format: str = "unknown"
    documents: list[PolicyDocument] = field(default_factory=list)
    patterns: list[TextPattern] = field(default_factory=list)
    items: list[Item] = field(default_factory=list)
    defaults: list[DefaultAction] = field(default_factory=list)
    schema_errors: list[SchemaError] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        out = {"translated": 0, "translated_with_note": 0, "untranslatable": 0}
        for item in self.items:
            out[item.status] += 1
        return out

    def untranslatable(self) -> list[Item]:
        return [i for i in self.items if i.status == "untranslatable"]

    def reject(self, item: Item, reason: str) -> None:
        """Turn a translated item back into an untranslatable one, removing its rules."""
        self.drop_rules(set(item.rules))
        item.status = "untranslatable"
        item.reason = reason
        item.effect = ""
        item.rules = []
        item.patterns = []

    def drop_rules(self, rule_ids: set[str]) -> None:
        for doc in self.documents:
            doc.rules = [r for r in doc.rules if r.id not in rule_ids]
        used = {
            r.when.detection.entity
            for doc in self.documents
            for r in doc.rules
            if r.when.detection and r.when.detection.entity
        }
        self.patterns = [p for p in self.patterns if p.entity in used]

    def to_json(self) -> dict[str, Any]:
        return {
            "format": self.format,
            "documents": [d.model_dump(exclude_none=True) for d in self.documents],
            "patterns": [p.to_json() for p in self.patterns],
            "items": [i.to_json() for i in self.items],
            "default_action": [d.to_json() for d in self.defaults],
            "unmatched_pass": any(d.unmatched_pass for d in self.defaults),
            "schema_errors": [e.to_json() for e in self.schema_errors],
            "errors": self.errors,
            "notes": self.notes,
            "summary": self.counts(),
        }


# ---------------------------------------------------------------------------
# Conditions, format-independent
# ---------------------------------------------------------------------------


@dataclass
class Draft:
    """One conjunction of conditions on its way to becoming a `Condition`."""

    #: (op, value): op in eq / startswith / endswith / contains / ne.
    tool: tuple[str, str] | None = None
    agent: tuple[str, str] | None = None
    argument: ArgumentCondition | None = None
    pii: bool = False
    #: (regex, case_sensitive)
    text: tuple[str, bool] | None = None
    #: A comparison of two fields, over the names `_eval_expr` knows.
    expr: str | None = None
    notes: list[str] = field(default_factory=list)

    def copy(self) -> Draft:
        return Draft(
            self.tool,
            self.agent,
            self.argument,
            self.pii,
            self.text,
            self.expr,
            list(self.notes),
        )

    def set_tool(self, op: str, value: str) -> None:
        if self.tool is not None:
            raise Untranslatable("tests the tool name twice in one condition")
        self.tool = (op, value)

    def set_agent(self, op: str, value: str) -> None:
        if self.agent is not None:
            raise Untranslatable("tests the agent twice in one condition")
        self.agent = (op, value)

    def set_argument(self, condition: ArgumentCondition) -> None:
        if self.argument is not None:
            raise Untranslatable(
                "compares more than one argument in one condition; a rule here tests one argument"
            )
        self.argument = condition

    def set_text(self, regex: str, case_sensitive: bool) -> None:
        if self.text is not None or self.pii:
            raise Untranslatable("tests the text twice in one condition")
        try:
            re.compile(regex if case_sensitive else f"(?i){regex}")
        except re.error as exc:
            raise Untranslatable(f"the regular expression does not compile here: {exc}") from exc
        self.text = (regex, case_sensitive)

    def set_pii(self) -> None:
        if self.text is not None or self.pii:
            raise Untranslatable("tests the text twice in one condition")
        self.pii = True

    @property
    def tool_or_agent_only(self) -> bool:
        return self.argument is None and self.text is None and not self.pii


def glob_escape(value: str) -> str:
    return re.sub(r"([*?\[])", r"[\1]", value)


def _glob(op: str, value: str) -> str | None:
    if op == "glob":
        return value
    escaped = glob_escape(value)
    return {
        "eq": escaped,
        "startswith": f"{escaped}*",
        "endswith": f"*{escaped}",
        "contains": f"*{escaped}*",
    }.get(op)


def _expr_term(name: str, op: str, value: str) -> str:
    if op == "glob":
        op, value = _simple_glob(value)
    lit = repr(value)
    body = {
        "eq": f"{name} == {lit}",
        "ne": f"{name} != {lit}",
        "startswith": f"{name}.startswith({lit})",
        "endswith": f"{name}.endswith({lit})",
        "contains": f"{lit} in {name}",
    }[op]
    return f"({name} is not None and {body})"


def _simple_glob(glob: str) -> tuple[str, str]:
    """A glob as (op, literal) when it is ``x``, ``x*``, ``*x`` or ``*x*``."""
    core = glob.strip("*")
    literal = re.sub(r"\[([*?\[])\]", r"\1", core)
    if re.search(r"(?<!\[)[*?\[]", re.sub(r"\[[*?\[]\]", "", core)):
        raise Untranslatable(f"the pattern `{glob}` cannot be written as an exception here")
    starts, ends = glob.startswith("*"), glob.endswith("*")
    if starts and ends:
        return "contains", literal
    if ends:
        return "startswith", literal
    if starts:
        return "endswith", literal
    return "eq", literal


def exception_expr(draft: Draft) -> str:
    parts = []
    if draft.tool:
        parts.append(_expr_term("tool", *draft.tool))
    if draft.agent:
        parts.append(_expr_term("agent", *draft.agent))
    if draft.expr:
        parts.append(f"({draft.expr})")
    return " and ".join(parts) if parts else "True"


def build_condition(draft: Draft, surfaces: list[str], entity: str | None) -> Condition:
    when: dict[str, Any] = {}
    if surfaces:
        when["surface"] = list(surfaces)
    exprs: list[str] = []
    for name, cond in (("tool", draft.tool), ("agent", draft.agent)):
        if cond is None:
            continue
        op, value = cond
        if op == "ne":
            # Their `!=` matches a deny rule when the field is absent; so does this.
            exprs.append(f"({name} is None or {name} != {value!r})")
        else:
            when[name] = _glob(op, value)
    if draft.expr:
        exprs.append(f"({draft.expr})")
    if exprs:
        when["expr"] = " and ".join(exprs)
    if draft.argument is not None:
        when["argument"] = draft.argument
    if draft.pii:
        when["detection"] = DetectionCondition(entity_prefix="PII")
    if entity:
        when["detection"] = DetectionCondition(entity=entity)
    return Condition(**when)


def _slug(text: str, limit: int = 48) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return (slug[:limit].rstrip("-")) or "rule"


class _Builder:
    """Accumulates rules and patterns for one document, keeping ids unique."""

    def __init__(self, translation: Translation, key: str) -> None:
        self.translation = translation
        self.key = key
        self.rules: list[Rule] = []
        self.ids: set[str] = set()
        self.exceptions: list[tuple[Item, list[Draft]]] = []

    def unique(self, base: str) -> str:
        rid, n = base, 2
        while rid in self.ids:
            rid, n = f"{base}-{n}", n + 1
        self.ids.add(rid)
        return rid

    def pattern_key(self, base: str) -> str:
        keys = {p.key for p in self.translation.patterns}
        stem = f"imp-{_slug(self.key, 20)}-{_slug(base, 30)}"[:58].rstrip("-")
        key, n = stem, 2
        while key in keys:
            key, n = f"{stem}-{n}", n + 1
        return key

    def add(
        self,
        item: Item,
        drafts: list[Draft],
        *,
        effect: str,
        surfaces: list[str],
        reason: str,
        base_id: str,
        description: str,
        enabled: bool = True,
    ) -> None:
        for i, draft in enumerate(drafts):
            rid = self.unique(base_id if len(drafts) == 1 else f"{base_id}.{i + 1}")
            entity = None
            if draft.text is not None:
                regex, case_sensitive = draft.text
                text_surfaces = [s for s in (surfaces or TEXT_SURFACES) if s in TEXT_SURFACES]
                pattern = TextPattern(
                    key=self.pattern_key(rid),
                    name=f"{item.source} (imported pattern)"[:200],
                    pattern=regex,
                    surfaces=text_surfaces or list(TEXT_SURFACES),
                    case_sensitive=case_sensitive,
                )
                self.translation.patterns.append(pattern)
                item.patterns.append(pattern.key)
                entity = pattern.entity
            self.rules.append(
                Rule(
                    id=rid,
                    description=description[:500],
                    when=build_condition(draft, surfaces, entity),
                    effect=effect,  # type: ignore[arg-type]
                    reason=reason[:500],
                    severity=SEVERITY.get(effect, "medium"),
                    enabled=enabled,
                )
            )
            item.rules.append(rid)
            for note in draft.notes:
                if note not in item.notes:
                    item.notes.append(note)
        item.effect = effect
        item.document = self.key
        item.status = "translated_with_note" if item.notes else "translated"

    def default_deny(self, surfaces: list[str], why: str) -> Rule | None:
        """The block rule for a default deny, carving out the allow rules it can."""
        terms: list[str] = []
        for item, drafts in self.exceptions:
            try:
                exprs = (
                    [exception_expr(d) for d in drafts]
                    if all(d.tool_or_agent_only for d in drafts)
                    else None
                )
            except Untranslatable:
                exprs = None
            if exprs is not None:
                terms += exprs
                item.status = "translated_with_note"
                item.effect = "allow"
                item.document = self.key
                item.skippable = False
                item.notes.append(
                    "an exception to the default deny: calls it matches are not blocked "
                    "by the default-deny rule (other block rules still apply)"
                )
            else:
                item.status = "untranslatable"
                item.reason = (
                    "an allow rule under a default deny can be carried over only when it "
                    "tests the tool or agent name; this one tests more, so the imported "
                    "policy blocks what it allowed (stricter, never looser)"
                )
        expr = f"not ({' or '.join(terms)})" if terms else None
        rid = self.unique("default-deny")
        rule = Rule(
            id=rid,
            description=f"Imported default_action: deny. {why}"[:500],
            when=Condition(surface=surfaces or None, expr=expr),
            effect="block",
            reason="No rule allowed this call (imported default deny)",
            severity="high",
        )
        self.rules.append(rule)
        return rule


# ---------------------------------------------------------------------------
# Rule YAML conditions
# ---------------------------------------------------------------------------

_PATH = r"(\w+(?:\.\w+)*)"
_EQ = re.compile(rf"^{_PATH}\s*(==|!=)\s*(.+)$")
_IN = re.compile(rf"^{_PATH}\s+in\s+\[([^\]]*)\]$")
_STR_OP = re.compile(rf"^{_PATH}\s+(contains|startswith|endswith)\s+(['\"])(.*)\3$")
_CMP = re.compile(rf"^{_PATH}\s*(>=|<=|>|<)\s*(-?\d+(?:\.\d+)?)$")
_BOOL = re.compile(rf"^{_PATH}$")
_QUOTED = re.compile(r"^(['\"])(.*)\1$")
_NUMBER = re.compile(r"^-?\d+(?:\.\d+)?$")
_EXPR_NAMES = {
    **{f: "tool" for f in TOOL_FIELDS},
    **{f: "agent" for f in AGENT_FIELDS},
    "surface": "surface",
    "stage": "surface",
    "environment": "environment",
    "env": "environment",
    "risk_tier": "risk_tier",
}


def _literal(text: str) -> tuple[Any, bool] | None:
    """(value, quoted) for a literal, or None when ``text`` is a field path."""
    text = text.strip()
    quoted = _QUOTED.match(text)
    if quoted:
        return quoted.group(2), True
    if _NUMBER.match(text):
        return (float(text) if "." in text else int(text)), False
    lowered = text.lower()
    if lowered in ("true", "false"):
        return lowered == "true", False
    if lowered in ("null", "none"):
        return None, False
    return None if re.match(rf"^{_PATH}$", text) else (text, False)


def _field_kind(path: str) -> tuple[str, str, list[str]]:
    """(kind, argument path, notes) for a context field."""
    if path in TOOL_FIELDS:
        return "tool", "", []
    if path in AGENT_FIELDS:
        return "agent", "", ["their agents are DIDs; here the agent is its slug — check the names"]
    if path in TEXT_FIELDS:
        return (
            "text",
            "",
            [f"`{path}` is matched against the text checked at this surface"],
        )
    if path in PII_FIELDS:
        return (
            "pii",
            "",
            [f"`{path}` becomes a PII detection here: our detectors decide what is PII"],
        )
    for prefix in ARGUMENT_PREFIXES:
        if path.startswith(prefix):
            return "argument", path[len(prefix) :], []
    return (
        "argument",
        path,
        [f"context field `{path}` is read as the tool-call argument `{path}`"],
    )


def _atom(text: str, draft: Draft, action: str) -> list[Draft]:
    """Add one atomic condition to ``draft``; a membership test may fan out."""
    text = text.strip()
    if text.startswith("(") and text.endswith(")"):
        raise Untranslatable(f"parentheses are not part of their condition syntax: {UNRECOGNISED}")

    match = _IN.match(text)
    if match:
        path, items_text = match.groups()
        items = [s.strip().strip("'\"") for s in items_text.split(",") if s.strip()]
        kind, arg, notes = _field_kind(path)
        if kind in ("tool", "agent", "text"):
            out = []
            for value in items:
                branch = draft.copy()
                out += _atom(f"{path} == {value!r}", branch, action)
            return out
        if kind == "pii":
            raise Untranslatable(f"`{path}` is a flag, not a value to look up in a list")
        draft.notes += notes
        draft.set_argument(ArgumentCondition(path=arg, op="in", value=items))
        return [draft]

    match = _STR_OP.match(text)
    if match:
        path, op, _q, value = match.groups()
        kind, arg, notes = _field_kind(path)
        draft.notes += notes
        if kind == "tool":
            draft.set_tool(op, value)
        elif kind == "agent":
            draft.set_agent(op, value)
        elif kind == "text":
            escaped = re.escape(value)
            draft.set_text(
                {"contains": escaped, "startswith": f"^{escaped}", "endswith": f"{escaped}$"}[op],
                True,
            )
        elif kind == "pii":
            raise Untranslatable(f"`{path}` is a flag; `{op}` does not apply to it")
        elif op == "contains":
            draft.notes.append(
                "`contains` ignores case here and is case-sensitive there, so it fires on more"
            )
            draft.set_argument(ArgumentCondition(path=arg, op="contains", value=value))
        else:
            regex = f"^{re.escape(value)}" if op == "startswith" else f"{re.escape(value)}$"
            draft.set_argument(ArgumentCondition(path=arg, op="matches", value=regex))
        return [draft]

    match = _CMP.match(text)
    if match:
        path, op, number = match.groups()
        kind, arg, notes = _field_kind(path)
        if kind != "argument":
            raise Untranslatable(f"compares `{path}` with a number, which it is not")
        draft.notes += notes
        draft.notes.append(
            "when the field is missing or not a number their deny rule fires and this one does not"
        )
        value = float(number) if "." in number else int(number)
        op_name = {">": "gt", ">=": "gte", "<": "lt", "<=": "lte"}[op]
        draft.set_argument(ArgumentCondition(path=arg, op=op_name, value=value))
        return [draft]

    match = _EQ.match(text)
    if match:
        path, op, rhs = match.groups()
        literal = _literal(rhs)
        if literal is None:
            return [_field_to_field(path, op, rhs.strip(), draft)]
        value, quoted = literal
        if not quoted:
            draft.notes.append(
                f"`{rhs.strip()}` is unquoted: {UNRECOGNISED}; here it is compared as a value"
            )
        kind, arg, notes = _field_kind(path)
        draft.notes += notes
        name = "eq" if op == "==" else "ne"
        if kind in ("tool", "agent"):
            if not isinstance(value, str):
                raise Untranslatable(f"compares the {kind} name with {rhs.strip()}")
            (draft.set_tool if kind == "tool" else draft.set_agent)(name, value)
        elif kind == "text":
            if name == "ne":
                raise Untranslatable(
                    f"`{path} != ...` fires on every text but one; there is no text condition "
                    "for that here"
                )
            draft.set_text(f"^{re.escape(str(value))}$", True)
        elif kind == "pii":
            if value is True and name == "eq":
                draft.set_pii()
            else:
                raise Untranslatable(f"`{path}` can only be required true here")
        else:
            if name == "ne":
                draft.notes.append(
                    "when the field is missing their deny rule fires and this one does not"
                )
            draft.set_argument(ArgumentCondition(path=arg, op=name, value=value))
        return [draft]

    match = _BOOL.match(text)
    if match:
        path = match.group(1)
        kind, arg, notes = _field_kind(path)
        draft.notes += notes
        if kind == "pii":
            draft.set_pii()
            return [draft]
        if kind != "argument":
            raise Untranslatable(f"`{path}` on its own is a truth test of a {kind} name")
        draft.notes.append("a bare field is a truth test there; here it must equal true")
        draft.set_argument(ArgumentCondition(path=arg, op="eq", value=True))
        return [draft]

    raise Untranslatable(f"unrecognised condition `{text}`: {UNRECOGNISED}")


def _field_to_field(left: str, op: str, right: str, draft: Draft) -> Draft:
    """``a == b`` with both sides fields. Expressible only over the expr names."""
    a, b = _EXPR_NAMES.get(left), _EXPR_NAMES.get(right)
    if not (a and b):
        raise Untranslatable(
            f"compares two fields (`{left} {op} {right}`); a condition here compares a "
            f"field with a value, and {UNRECOGNISED}"
        )
    if draft.expr is not None:
        raise Untranslatable("compares fields with each other more than once")
    draft.expr = f"{a} is not None and {b} is not None and {a} {op} {b}"
    draft.notes.append(
        f"compares two fields (`{left} {op} {right}`): their evaluator cannot and treats it "
        "as unrecognised; here it is an `expr` condition, evaluated by the native engine"
    )
    return draft


def parse_condition(condition: str, action: str) -> list[Draft]:
    """Their condition string as a disjunction of drafts.

    Mirrors their split: `` or `` first, then `` and `` — so a condition reads here
    the way it reads there.
    """
    condition = condition.strip()
    if not condition:
        raise Untranslatable("empty condition")
    if len(condition) > 2000:
        raise Untranslatable("condition longer than their 2000-character limit")
    drafts: list[Draft] = []
    for branch in condition.split(" or "):
        current = [Draft()]
        for atom in branch.split(" and "):
            current = [d for draft in current for d in _atom(atom, draft, action)]
        drafts += current
    return drafts


# ---------------------------------------------------------------------------
# Rule YAML
# ---------------------------------------------------------------------------

SUPPORTED_API_VERSIONS = {"governance.toolkit/v1", "1.0"}


def _rules_yaml(data: dict[str, Any], out: Translation) -> None:
    out.format = "rules"
    name = str(data.get("name") or "imported-policy")
    api_version = data.get("apiVersion")
    if api_version is not None and str(api_version) not in SUPPORTED_API_VERSIONS:
        out.errors.append(
            f"apiVersion '{api_version}' is not one this importer reads "
            f"({', '.join(sorted(SUPPORTED_API_VERSIONS))})"
        )
        return
    default = str(data.get("default_action", "deny")).lower()
    if default not in ("allow", "deny"):
        out.errors.append(f"default_action must be allow or deny, not '{default}'")
        return

    key = f"imported-{_slug(name, 40)}"
    builder = _Builder(out, key)
    rules = data.get("rules") or []
    if not isinstance(rules, list):
        out.errors.append("`rules` must be a list")
        return

    stage_surfaces: list[str] = []
    for index, raw in enumerate(rules):
        item = Item(source=f"rule {index + 1}", status="untranslatable")
        out.items.append(item)
        if not isinstance(raw, dict):
            item.reason = "not a rule (expected a mapping)"
            continue
        item.source = str(raw.get("name") or raw.get("tool") or f"rule {index + 1}")
        action = str(raw.get("action", "deny")).lower()
        item.source_effect = action
        stage = str(raw.get("stage", "pre_tool"))
        surface = STAGE_SURFACE.get(stage)
        if surface is None:
            item.reason = f"unknown stage '{stage}'"
            continue
        if surface not in stage_surfaces:
            stage_surfaces.append(surface)
        try:
            drafts = _rule_drafts(raw, item)
        except Untranslatable as exc:
            item.reason = str(exc)
            continue
        if raw.get("limit") or action == "rate_limit":
            item.reason = (
                f"rate limit ({raw.get('limit') or 'unspecified'}): a rule here does not "
                "count calls; set an agent budget instead"
            )
            continue
        enabled = bool(raw.get("enabled", True))
        description = str(raw.get("description") or "").strip()
        condition = item.condition
        if action == "allow":
            if default == "deny":
                builder.exceptions.append((item, drafts))
                continue
            builder.add(
                item,
                drafts,
                effect="allow",
                surfaces=[surface],
                reason=str(raw.get("reason") or f"allowed by imported rule {item.source}"),
                base_id=_slug(item.source),
                description=description or f"Imported allow: {condition}",
                enabled=enabled,
            )
            item.notes.append(
                "an allow rule only records here: the strongest effect wins, so it never "
                "overrides a block (their priority order does not apply)"
            )
            item.status = "translated_with_note"
            continue
        effect = ACTION_EFFECT.get(action)
        if effect is None:
            item.reason = f"unknown action '{action}'"
            continue
        builder.add(
            item,
            drafts,
            effect=effect,
            surfaces=[surface],
            reason=str(raw.get("reason") or raw.get("message") or f"imported rule {item.source}"),
            base_id=_slug(item.source),
            description=description or f"Imported {action}: {condition}",
            enabled=enabled,
        )
        if action in ("warn", "log"):
            item.notes.append(f"`{action}` has no enforcing equivalent: recorded when it fires")
            item.status = "translated_with_note"
        if action == "require_approval":
            approvers = raw.get("approvers") or []
            carried = f"; their approvers ({', '.join(map(str, approvers))}) are not carried"
            item.notes.append("escalates to the approval queue" + (carried if approvers else ""))
            item.status = "translated_with_note"
        if not enabled:
            item.notes.append("disabled in the source; imported disabled")
            item.status = "translated_with_note"

    _list_sections(data, builder, out, default)
    _finish(out, builder, data, name, default, stage_surfaces or ["tool_args"], source="rules")


#: Top-level keys of a rule file that describe it rather than decide anything.
RULES_INFO_KEYS = {
    "apiVersion",
    "version",
    "name",
    "description",
    "disclaimer",
    "metadata",
    "extends",
    "agent",
    "agents",
    "scope",
    "default_action",
    "rules",
    "created_at",
    "updated_at",
    "mode",
    "kind",
}
#: List sections some integrations use instead of `rules`.
LIST_SECTIONS = {
    "blocked_tools": "tool",
    "allowed_tools": "tool",
    "blocked_content_patterns": "text",
    "blocked_argument_patterns": "text",
}


def _list_sections(data: dict[str, Any], builder: _Builder, out: Translation, default: str) -> None:
    """``blocked_tools`` / ``allowed_tools`` / ``blocked_*_patterns``; anything else
    unknown is reported, so no section is dropped without a word."""
    for section, value in data.items():
        if section in RULES_INFO_KEYS:
            continue
        kind = LIST_SECTIONS.get(section)
        if kind is None or not isinstance(value, list):
            out.items.append(
                Item(
                    source=str(section),
                    status="untranslatable",
                    reason=f"`{section}` is not a rule section this importer reads",
                )
            )
            continue
        for entry in value:
            entry = str(entry)
            item = Item(
                source=f"{section}: {entry}",
                status="untranslatable",
                source_effect="allow" if section == "allowed_tools" else "deny",
                condition=entry,
            )
            out.items.append(item)
            draft = Draft()
            try:
                if kind == "tool":
                    draft.tool = ("glob", entry)
                    surfaces = ["tool_args"]
                else:
                    draft.set_text(entry, False)
                    surfaces = ["tool_args"] if "argument" in section else ["input", "tool_args"]
                    draft.notes.append("matched ignoring case, as the source does")
            except Untranslatable as exc:
                item.reason = str(exc)
                continue
            if section == "allowed_tools":
                if default == "deny":
                    builder.exceptions.append((item, [draft]))
                else:
                    item.status = "translated_with_note"
                    item.notes.append("the default already allows; nothing to import")
                continue
            builder.add(
                item,
                [draft],
                effect="block",
                surfaces=surfaces,
                reason=f"Blocked by imported {section}: {entry}",
                base_id=_slug(f"{section}-{entry}"),
                description=f"Imported {section}: {entry}",
            )


def _rule_drafts(raw: dict[str, Any], item: Item) -> list[Draft]:
    """Drafts for a rule with a `condition` string or a `tool` key."""
    action = str(raw.get("action", "deny")).lower()
    if "condition" in raw:
        condition = str(raw.get("condition") or "")
        item.condition = condition
        return parse_condition(condition, action)
    if "tool" in raw:
        tool = str(raw["tool"])
        item.condition = f"tool: {tool}"
        if raw.get("conditions"):
            raise Untranslatable(
                f"`conditions` ({', '.join(sorted(_keys(raw['conditions'])))}) are not "
                "translated; the rule would fire on more calls than theirs, so it is left out"
                if action == "allow"
                else f"`conditions` ({', '.join(sorted(_keys(raw['conditions'])))}) have no "
                "equivalent here"
            )
        draft = Draft()
        if any(ch in tool for ch in "*?["):
            draft.tool = ("glob", tool)
        else:
            draft.set_tool("eq", tool)
        return [draft]
    if "pattern" in raw:
        pattern = str(raw["pattern"])
        item.condition = f"pattern: {pattern}"
        draft = Draft()
        draft.set_text(pattern, True)
        draft.notes.append(
            "a source-code check there; here the pattern is matched against agent text"
        )
        return [draft]
    raise Untranslatable("has no `condition`, `tool` or `pattern`")


def _keys(value: Any) -> list[str]:
    if isinstance(value, dict):
        return [str(k) for k in value]
    if isinstance(value, list):
        return [k for v in value for k in _keys(v)] or ["?"]
    return [str(value)]


def _finish(
    out: Translation,
    builder: _Builder,
    data: dict[str, Any],
    name: str,
    default: str,
    default_surfaces: list[str],
    *,
    source: str,
) -> None:
    if default == "deny":
        builder.default_deny(
            default_surfaces,
            "Calls no rule allowed are blocked, as they were there.",
        )
        out.defaults.append(
            DefaultAction(
                document=builder.key,
                source="deny",
                effect="block",
                unmatched_pass=False,
                note=(
                    "Unmatched calls are blocked by the `default-deny` rule on "
                    f"{', '.join(default_surfaces)}."
                ),
            )
        )
    elif default == "allow":
        out.defaults.append(
            DefaultAction(
                document=builder.key,
                source="allow",
                effect="allow",
                unmatched_pass=True,
                note=(
                    "default_action: allow — a call no rule matches passes. That is the "
                    "source policy's choice, kept as is; it is not a safe default."
                ),
            )
        )
    else:
        out.defaults.append(
            DefaultAction(
                document=builder.key,
                source="unknown",
                effect="allow",
                unmatched_pass=True,
                note=(
                    "The default could not be read from the policy, so a call no rule "
                    "matches passes. Check what the source did."
                ),
            )
        )
    agents = [str(a) for a in (data.get("agents") or [])]
    if data.get("agent"):
        agents.append(str(data["agent"]))
    scope: dict[str, Any] = {}
    if agents and "*" not in agents:
        scope["agents"] = agents
        out.notes.append(
            "The policy is scoped to their agent identifiers (DIDs); here scope matches "
            "agent slugs. Rename them before enforcing."
        )
    if not builder.rules:
        out.notes.append(f"Nothing from `{name}` translated, so no policy is created for it.")
        return
    out.documents.append(
        PolicyDocument(
            key=builder.key,
            name=f"{name} (imported)",
            description=str(
                data.get("description") or (data.get("metadata") or {}).get("description") or ""
            ).strip()[:1000],
            mode="observe",
            default_effect="allow",
            scope=scope,
            rules=builder.rules,
        )
    )
    if data.get("extends"):
        out.notes.append(
            "`extends` names parent policies that are not imported with this file; "
            "import each parent too."
        )


# ---------------------------------------------------------------------------
# Manifests and Rego
# ---------------------------------------------------------------------------

_ACTION_REF = r"(?:legacy_input|input)\.action"
_PARAM_REF = r"(?:legacy_input|input)\.params\.([A-Za-z_][A-Za-z0-9_.]*)"
_TEXT_REFS = {
    "input.output",
    "legacy_input.output",
    "input.content",
    "input.text",
    "input.policy_target.value",
}


def _is_text_ref(expr: str, module: RegoModule) -> bool | None:
    """True for the policy target's text, None for its lower-cased text, else False."""
    expr = expr.strip()
    wrapped = re.match(r'^sprintf\("%v",\s*\[(.+)\]\)$', expr)
    if wrapped:
        expr = wrapped.group(1).strip()
    lowered = re.match(r"^lower\((.+)\)$", expr)
    if lowered:
        return None if _is_text_ref(lowered.group(1), module) else False
    return expr in _TEXT_REFS or expr in module.text_aliases


def _split_args(text: str) -> list[str]:
    return [p.strip() for p in rego_subset.split_body(text, separators=",")]


def _call(statement: str, name: str) -> list[str] | None:
    prefix = f"{name}("
    if not (statement.startswith(prefix) and statement.endswith(")")):
        return None
    inner = statement[len(prefix) : -1]
    # The whole statement must be one call: the closing paren is the first one at depth 0.
    depth = 0
    for i, ch in enumerate(statement[len(prefix) - 1 :]):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0 and i != len(statement) - len(prefix):
                return None
    return _split_args(inner)


def _regex_to_globs(pattern: str) -> list[str]:
    """A tool-name regex as globs, when it is an alternation of literals."""
    start = pattern.startswith("^")
    end = pattern.endswith("$") and not pattern.endswith("\\$")
    core = pattern[1 if start else 0 : -1 if end else None]
    group = re.match(r"^\((?:\?:)?(.*)\)$", core)
    if group and "(" not in group.group(1):
        core = group.group(1)
    globs = []
    for alt in core.split("|"):
        literal = alt.replace("\\.", ".").replace("\\-", "-")
        if not re.match(r"^[A-Za-z0-9_.:\-]+$", literal):
            raise Untranslatable(
                f"matches the action name with the regular expression `{pattern}`; a tool "
                "condition here is a glob, and this one has no glob equivalent"
            )
        escaped = glob_escape(literal)
        globs.append(("" if start else "*") + escaped + ("" if end else "*"))
    return globs


def _rego_value(text: str, consts: dict[str, Any]) -> tuple[Any, bool]:
    """(value, ok) for a Rego literal or a constant set name."""
    text = text.strip()
    literal = rego_subset.string_literal(text)
    if literal is not None:
        return literal, True
    if _NUMBER.match(text):
        return (float(text) if "." in text else int(text)), True
    if text in ("true", "false"):
        return text == "true", True
    if text == "null":
        return None, True
    if text in consts:
        value = consts[text]
        return (list(value) if isinstance(value, list) else value), True
    collection = rego_subset.string_collection(text)
    if collection is not None:
        return collection, True
    return None, False


def _apply_body(
    statements: list[str],
    drafts: list[Draft],
    module: RegoModule,
    consts: dict[str, Any],
    depth: int = 0,
) -> list[Draft]:
    """Apply a rule body: constants, ``some x in set`` loops and boolean helpers inline."""
    if depth > 8:
        raise Untranslatable("helper rules nest too deeply to follow")
    for index, statement in enumerate(statements):
        s = " ".join(statement.split())
        loop = re.fullmatch(r"some (\w+) in (.+)", s)
        if loop:
            values, ok = _rego_value(loop.group(2), consts)
            if not ok or not isinstance(values, list):
                raise Untranslatable(f"`{s}` loops over something that is not a set of names")
            out: list[Draft] = []
            for value in values:
                literal = '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'
                rest = [
                    re.sub(rf"\b{re.escape(loop.group(1))}\b", lambda _m, v=literal: v, r)
                    for r in statements[index + 1 :]
                ]
                out += _apply_body(rest, [d.copy() for d in drafts], module, consts, depth + 1)
            return out
        assign = re.fullmatch(r"(\w+) :?= (.+)", s)
        if assign:
            value = rego_subset.constant_value(assign.group(2))
            if value is not None:
                consts = {**consts, assign.group(1): value}
                continue
        if s in module.helpers:
            out = []
            for body in module.helpers[s]:
                out += _apply_body(body, [d.copy() for d in drafts], module, consts, depth + 1)
            drafts = out
            continue
        drafts = _rego_statement(statement, drafts, module, consts)
    return drafts


def _rego_statement(
    statement: str, drafts: list[Draft], module: RegoModule, consts: dict[str, Any]
) -> list[Draft]:
    """Apply one body statement to every draft; may fan out on a set membership."""
    s = " ".join(statement.split())

    args = _call(s, "regex.match")
    if args is not None and len(args) == 2:
        pattern = rego_subset.string_literal(args[0])
        if pattern is None and isinstance(consts.get(args[0]), str):
            pattern = consts[args[0]]
        if pattern is None:
            raise Untranslatable(f"`{s}` matches a pattern that is not a literal")
        if re.fullmatch(_ACTION_REF, args[1]):
            globs = _regex_to_globs(pattern)
            out = []
            for d in drafts:
                for glob in globs:
                    if d.tool is not None:
                        raise Untranslatable("tests the action name twice")
                    branch = d.copy()
                    branch.tool = ("glob", glob)
                    out.append(branch)
            return out
        text = _is_text_ref(args[1], module)
        if text is False:
            raise Untranslatable(f"`{s}` matches a value other than the policy target's text")
        regex, case_sensitive = _go_regex(pattern, case_sensitive=text is True)
        for d in drafts:
            d.set_text(regex, case_sensitive)
        return drafts

    for fn in ("contains", "startswith", "endswith"):
        args = _call(s, fn)
        if args is None or len(args) != 2:
            continue
        needle = rego_subset.string_literal(args[1])
        if needle is None:
            raise Untranslatable(f"`{s}` tests for a value that is not a literal")
        if re.fullmatch(_ACTION_REF, args[0]):
            op = fn
            for d in drafts:
                d.set_tool(op, needle)
            return drafts
        text = _is_text_ref(args[0], module)
        if text is False:
            raise Untranslatable(f"`{s}` tests a value other than the policy target's text")
        escaped = re.escape(needle)
        regex = {"contains": escaped, "startswith": f"^{escaped}", "endswith": f"{escaped}$"}[fn]
        for d in drafts:
            d.set_text(regex, text is True)
        return drafts

    match = re.fullmatch(rf"{_ACTION_REF}\s*(==|!=)\s*(.+)", s)
    if match:
        value, ok = _rego_value(match.group(2), consts)
        if not ok or not isinstance(value, str):
            raise Untranslatable(f"`{s}` compares the action with something other than a name")
        for d in drafts:
            d.set_tool("eq" if match.group(1) == "==" else "ne", value)
        return drafts

    match = re.fullmatch(rf"{_ACTION_REF}\s+in\s+(.+)", s)
    if match:
        values, ok = _rego_value(match.group(1), consts)
        if not ok or not isinstance(values, list):
            raise Untranslatable(f"`{s}` tests membership in something that is not a set of names")
        if not values:
            raise Untranslatable(f"`{s}` tests membership in an empty set; it never fires")
        out = []
        for d in drafts:
            for value in values:
                branch = d.copy()
                branch.set_tool("eq", value)
                out.append(branch)
        return out

    match = re.fullmatch(rf"{_PARAM_REF}\s*(==|!=|>=|<=|>|<)\s*(.+)", s)
    if match:
        path, op, rhs = match.groups()
        value, ok = _rego_value(rhs, consts)
        if not ok or isinstance(value, list):
            raise Untranslatable(f"`{s}` compares an argument with something that is not a value")
        op_name = {"==": "eq", "!=": "ne", ">": "gt", ">=": "gte", "<": "lt", "<=": "lte"}[op]
        note = None
        if op == "!=" and value is not None:
            note = "when the argument is missing theirs fires and this does not"
        for d in drafts:
            d.set_argument(ArgumentCondition(path=path, op=op_name, value=value))
            if note:
                d.notes.append(note)
        return drafts

    match = re.fullmatch(rf"{_PARAM_REF}\s+in\s+(.+)", s)
    if match:
        values, ok = _rego_value(match.group(2), consts)
        if not ok or not isinstance(values, list):
            raise Untranslatable(f"`{s}` tests membership in something that is not a set")
        for d in drafts:
            d.set_argument(ArgumentCondition(path=match.group(1), op="in", value=values))
        return drafts

    match = re.fullmatch(_PARAM_REF, s)
    if match:
        for d in drafts:
            d.set_argument(ArgumentCondition(path=match.group(1), op="eq", value=True))
            d.notes.append("a bare argument is a truth test there; here it must equal true")
        return drafts

    if s.startswith("not "):
        raise Untranslatable(f"`{s}`: a negated condition has no equivalent here")
    if re.search(r"\b(?:legacy_input|input)\.context\b|\bsnapshot\b|\benvelope\b|\bbudgets?\b", s):
        raise Untranslatable(
            f"`{s}` reads the call's context or budget, which a policy condition here does not see"
        )
    raise Untranslatable(f"`{s}` has no equivalent condition here")


def _go_regex(pattern: str, *, case_sensitive: bool) -> tuple[str, bool]:
    """A Go RE2 pattern as a Python one: a leading ``(?i)`` becomes the rule's flag."""
    if pattern.startswith("(?i)"):
        pattern, case_sensitive = pattern[4:], False
    return pattern.replace("\\z", "\\Z"), case_sensitive


def _reason_from(rule: RegoRule) -> tuple[str, list[str]]:
    """The message a rule adds, and the body without the statement that sets it."""
    head = rego_subset.string_literal(rule.head)
    body = list(rule.body)
    if head is not None:
        return head, body
    rest: list[str] = []
    reason = ""
    for statement in body:
        match = re.match(rf"^{re.escape(rule.head)}\s*:=\s*(.+)$", statement.strip(), re.S)
        if match:
            value = match.group(1).strip()
            literal = rego_subset.string_literal(value)
            if literal is None:
                fmt = re.match(r"^sprintf\(\s*(\"(?:[^\"\\]|\\.)*\")", value)
                literal = rego_subset.string_literal(fmt.group(1)) if fmt else None
            reason = literal or value
            continue
        rest.append(statement)
    return reason, rest


def _package_default(module_group: list[RegoModule], entry: str) -> str:
    """allow / deny / unknown: what the package decides when no rule fires."""
    text = "\n".join(s for m in module_group for s in m.statements)
    if re.search(r'"Default deny"', text) or re.search(
        r'"decision":\s*"deny"[^}]*\}\s*if\s*\{[^}]*count\(allows?\)\s*==\s*0', text, re.S
    ):
        return "deny"
    if (
        "acs.normalize" in text
        or re.search(r'"decision":\s*"allow"', text)
        or re.search(r'decision\s*:=\s*"allow"', text)
    ):
        return "allow"
    return "unknown"


def _manifest(data: dict[str, Any], files: dict[str, str], out: Translation) -> None:
    out.format = "manifest"
    out.schema_errors = validate(data)
    if out.schema_errors:
        out.errors.append(
            f"the manifest does not match the published schema ({len(out.schema_errors)} "
            "problem(s)); fix it and try again"
        )
        return

    metadata = data.get("metadata") or {}
    name = str(metadata.get("name") or "imported-manifest")
    modules = rego_subset.parse_bundle(files)
    policies = data.get("policies") or {}
    points = data.get("intervention_points") or {}

    # Which packages each policy is queried at, and from which points.
    bindings: dict[str, dict[str, list[str]]] = {}
    binding_queries: dict[str, set[str]] = {}
    for point, spec in points.items():
        binding = (spec or {}).get("policy") or {}
        policy_id = binding.get("id")
        if not policy_id:
            continue
        query = binding.get("query") or (policies.get(policy_id) or {}).get("query") or ""
        package = query.removeprefix("data.").rsplit(".", 1)[0] if query else ""
        bindings.setdefault(policy_id, {}).setdefault(package, []).append(point)
        if query:
            binding_queries.setdefault(package, set()).add(query.rsplit(".", 1)[-1])
        if point not in POINT_SURFACE:
            out.notes.append(
                f"intervention point `{point}` has no surface here; rules bound only to it "
                "are not checked"
            )
        if spec.get("annotations"):
            for label in spec["annotations"]:
                out.items.append(
                    Item(
                        source=f"{point}: annotation {label}",
                        status="untranslatable",
                        source_effect="annotation",
                        reason=(
                            "annotations call a classifier or model before the policy runs; "
                            "switch on a detector for the same job instead"
                        ),
                    )
                )

    for policy_id, spec in policies.items():
        kind = str((spec or {}).get("type"))
        key = f"imported-{_slug(name, 30)}" + (
            f"-{_slug(policy_id, 20)}" if len(policies) > 1 else ""
        )
        if kind != "rego":
            out.items.append(
                Item(
                    source=policy_id,
                    status="untranslatable",
                    source_effect=kind,
                    reason=(
                        "Cedar policies are not translated; write the equivalent rules here"
                        if kind == "cedar"
                        else f"a `{kind}` policy runs host code; there is nothing to translate"
                    ),
                )
            )
            continue
        if policy_id not in bindings:
            out.notes.append(f"policy `{policy_id}` is not bound to any intervention point")
            continue
        if not modules:
            out.items.append(
                Item(
                    source=policy_id,
                    status="untranslatable",
                    source_effect="rego",
                    reason=(
                        f"the Rego bundle (`{spec.get('bundle') or spec.get('bundle_url') or '?'}`)"
                        " was not provided; add its .rego files to translate the rules"
                    ),
                )
            )
            continue
        builder = _Builder(out, key)
        default = "allow"
        surfaces_all: list[str] = []
        for package, bound_points in bindings[policy_id].items():
            group = [m for m in modules if m.package == package]
            if not group:
                out.items.append(
                    Item(
                        source=f"{policy_id}: {package or '(no query)'}",
                        status="untranslatable",
                        source_effect="rego",
                        reason=f"no module in the bundle declares package `{package}`",
                    )
                )
                continue
            surfaces = [POINT_SURFACE[p] for p in bound_points if p in POINT_SURFACE]
            for s in surfaces:
                if s not in surfaces_all:
                    surfaces_all.append(s)
            package_default = _package_default(group, "")
            if package_default == "deny" or (package_default == "unknown" and default != "deny"):
                default = package_default
            before = len(out.items)
            for module in group:
                for rule in module.rules:
                    _rego_rule(rule, module, builder, surfaces, out)
            if len(out.items) == before:
                _report_unread_package(group, package, bound_points, binding_queries, out)
        _finish(out, builder, data, name, default, surfaces_all or ["tool_args"], source="manifest")

    if data.get("approval"):
        out.notes.append(
            "The manifest's `approval` section is host configuration; escalated calls go "
            "to the approval queue here."
        )
    if data.get("tools"):
        out.notes.append(
            "`tools` (clearances and security labels) are not imported; declare the tools "
            "here to give them an impact level."
        )


def _report_unread_package(
    group: list[RegoModule],
    package: str,
    points: list[str],
    binding_queries: dict[str, set[str]],
    out: Translation,
) -> None:
    """A bound package with no decision-set rules: report what decides instead."""
    entries = binding_queries.get(package, set())
    found = False
    for module in group:
        for statement in module.statements:
            head = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*:?=", statement)
            if not head or head.group(1) not in entries:
                continue
            rhs = statement[head.end() :].split()
            if rhs and rhs[0] in entries:
                continue  # dispatch to another entry rule, reported on its own
            found = True
            first = " ".join(statement.split())[:160]
            out.items.append(
                Item(
                    source=f"{package}.{head.group(1)}",
                    status="untranslatable",
                    source_effect="rego",
                    condition=first,
                    file=module.file,
                    reason=(
                        "decides with a conditional verdict rule; only decision-set rules "
                        "(`deny contains msg if { ... }`) are translated"
                    ),
                )
            )
    if not found:
        out.items.append(
            Item(
                source=f"{package} ({', '.join(points)})",
                status="untranslatable",
                source_effect="rego",
                reason="no decision rule in this package could be read",
            )
        )


def _rego_rule(
    rule: RegoRule, module: RegoModule, builder: _Builder, surfaces: list[str], out: Translation
) -> None:
    effect = SET_EFFECT.get(rule.name)
    if effect is None:
        return  # a helper set feeding other rules, not a decision
    reason, body = _reason_from(rule)
    item = Item(
        source=f"{module.package}.{rule.name}: {reason or rule.head}"[:200],
        status="untranslatable",
        source_effect=rule.name,
        condition="; ".join(" ".join(s.split()) for s in body)[:600],
        line=rule.line,
        file=rule.file,
    )
    if any(i.source == item.source and i.condition == item.condition for i in out.items):
        return  # the same package bound at several points
    out.items.append(item)
    try:
        drafts = _apply_body(body, [Draft()], module, dict(module.constants))
    except Untranslatable as exc:
        item.reason = str(exc)
        return
    if any(d.tool is None and d.argument is None and d.text is None and not d.pii for d in drafts):
        item.reason = "no condition this importer could read; it would fire on every call"
        return
    rule_surfaces = list(surfaces)
    if any(d.tool or d.argument for d in drafts):
        if "tool_args" not in surfaces:
            item.reason = (
                "tests the action or its arguments, but the policy is not bound to pre_tool_call"
            )
            return
        if not any(d.text for d in drafts):
            rule_surfaces = ["tool_args"]
    if effect == "allow-exception":
        builder.exceptions.append((item, drafts))
        return
    base = _slug(f"{rule.name}-{reason or rule.head}", 56)
    builder.add(
        item,
        drafts,
        effect=effect,
        surfaces=rule_surfaces,
        reason=reason or f"imported from {module.package}.{rule.name}",
        base_id=base,
        description=f"Imported from {module.package} ({rule.file}:{rule.line})",
    )
    if rule.name in ("audit", "audits", "warn", "warnings", "warning"):
        item.notes.append(
            "an audit/warn decision has no enforcing equivalent: recorded when it fires"
        )
        item.status = "translated_with_note"
    if any(d.text for d in drafts) and len(rule_surfaces) > 1:
        note = (
            f"the text pattern is checked on {', '.join(rule_surfaces)}, every surface the "
            "policy is bound to"
        )
        if note not in item.notes:
            item.notes.append(note)
            item.status = "translated_with_note"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def bundle_files(manifest_path: Path) -> dict[str, str]:
    """The ``.rego`` files of every local bundle a manifest names, by relative path.

    Bundles are directories next to the manifest. A ``bundle_url`` is never fetched:
    importing is offline, and a remote bundle is added by downloading it first.
    """
    try:
        data = yaml.safe_load(manifest_path.read_text())
    except (OSError, yaml.YAMLError):
        return {}
    if not isinstance(data, dict):
        return {}
    files: dict[str, str] = {}
    for spec in (data.get("policies") or {}).values():
        bundle = (spec or {}).get("bundle") if isinstance(spec, dict) else None
        if not bundle:
            continue
        root = (manifest_path.parent / str(bundle)).resolve()
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*.rego")):
            files[str(path.relative_to(root))] = path.read_text(errors="replace")
    return files


def detect_format(data: Any) -> str:
    if not isinstance(data, dict):
        return "unknown"
    if "agent_control_specification_version" in data:
        return "manifest"
    rules = data.get("rules")
    if isinstance(rules, list) and any(
        isinstance(r, dict) and ("condition" in r or "tool" in r or "pattern" in r) for r in rules
    ):
        return "rules"
    if "apiVersion" in data or "default_action" in data:
        return "rules"
    return "unknown"


def translate(source: str, files: dict[str, str] | None = None) -> Translation:
    """Read ``source`` (YAML or JSON) and translate it. Never raises on bad input."""
    out = Translation()
    try:
        data = yaml.safe_load(source)
    except yaml.YAMLError as exc:
        out.errors.append(f"not YAML or JSON: {' '.join(str(exc).split())[:200]}")
        return out
    kind = detect_format(data)
    try:
        if kind == "manifest":
            _manifest(data, files or {}, out)
        elif kind == "rules":
            _rules_yaml(data, out)
        else:
            _unknown(data, out)
    except Exception as exc:  # noqa: BLE001 — a plan must come back, with the reason
        out.errors.append(f"could not translate: {type(exc).__name__}: {exc}")
    return out


_INFO_KEYS = {"version", "name", "description", "disclaimer", "metadata", "apiVersion", "kind"}


def _unknown(data: Any, out: Translation) -> None:
    out.format = "unknown"
    if not isinstance(data, dict):
        out.errors.append(
            "expected a policy with `rules` and `default_action`, or a policy manifest "
            "with `agent_control_specification_version`"
        )
        return
    sections = [k for k in data if k not in _INFO_KEYS]
    if not sections:
        out.errors.append("no rules found")
        return
    for section in sections:
        out.items.append(
            Item(
                source=str(section),
                status="untranslatable",
                reason=(
                    "this section configures a specific checker (patterns, thresholds or "
                    "a SQL/sandbox profile), not policy rules; nothing is imported from it"
                ),
            )
        )


__all__ = [
    "DefaultAction",
    "bundle_files",
    "Item",
    "TextPattern",
    "Translation",
    "detect_format",
    "translate",
]
