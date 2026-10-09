"""Read the decision rules out of a Rego policy bundle, without evaluating Rego.

Policy manifests bind each intervention point to a Rego package, and the rules
that matter are its partial-set rules: ``deny contains msg if { ... }``,
``escalations contains "reason" if { ... }`` and so on, combined by an entry rule
into one decision. This module splits a module into those rules and their body
statements, plus the string-set constants they test against. It understands the
shape, not the language: translating a statement is `agent_governance.py`'s job,
and anything it cannot translate is reported there, statement and all.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

_IDENT = r"[A-Za-z_][A-Za-z0-9_]*"
_SET_RULE = re.compile(rf"^({_IDENT})\s+contains\s+(.+?)\s+if\s*\{{(.*)\}}\s*$", re.S)
_SET_RULE_ONE_LINE = re.compile(rf"^({_IDENT})\s+contains\s+(.+?)\s+if\s+(.+)$", re.S)
_SET_RULE_LEGACY = re.compile(rf"^({_IDENT})\[(.+?)\]\s*(?:if\s*)?\{{(.*)\}}\s*$", re.S)
_ASSIGN = re.compile(rf"^({_IDENT})\s*:?=\s*(.+)$", re.S)
_HELPER = re.compile(rf"^({_IDENT})\s+if\s*\{{(.*)\}}\s*$", re.S)
_NUMBER = re.compile(r"^-?\d+(?:\.\d+)?$")
_STRING = re.compile(r'^"((?:[^"\\]|\\.)*)"$|^`([^`]*)`$')


@dataclass
class RegoRule:
    #: The set it adds to: ``deny``, ``escalations``, ``audit`` …
    name: str
    #: What it adds: a quoted message or a variable bound in the body.
    head: str
    body: list[str]
    line: int
    source: str
    file: str = ""


@dataclass
class RegoModule:
    package: str
    file: str = ""
    rules: list[RegoRule] = field(default_factory=list)
    #: ``name := {"a", "b"}`` (string sets and arrays) and ``name := "x"`` / ``10``.
    constants: dict[str, Any] = field(default_factory=dict)
    #: Boolean helper rules, ``name if { ... }``: each definition's body. Several
    #: definitions of one name are alternatives (OR).
    helpers: dict[str, list[list[str]]] = field(default_factory=dict)
    #: Every other top-level statement, kept to work out the package's default.
    statements: list[str] = field(default_factory=list)
    #: Names defined from the policy target's text (``_output_text := v if {...}``).
    text_aliases: set[str] = field(default_factory=set)


def strip_comments(text: str) -> str:
    """Drop ``#`` comments, leaving strings and raw strings alone."""
    out: list[str] = []
    for line in text.splitlines():
        quote: str | None = None
        escaped = False
        cut = len(line)
        for i, ch in enumerate(line):
            if quote:
                if escaped:
                    escaped = False
                elif ch == "\\" and quote == '"':
                    escaped = True
                elif ch == quote:
                    quote = None
            elif ch in '"`':
                quote = ch
            elif ch == "#":
                cut = i
                break
        out.append(line[:cut])
    return "\n".join(out)


def _depth_change(line: str, quote: str | None) -> tuple[int, str | None]:
    depth = 0
    escaped = False
    for ch in line:
        if quote:
            if escaped:
                escaped = False
            elif ch == "\\" and quote == '"':
                escaped = True
            elif ch == quote:
                quote = None
            continue
        if ch in '"`':
            quote = ch
        elif ch in "{[(":
            depth += 1
        elif ch in "}])":
            depth -= 1
    return depth, quote


def split_statements(text: str) -> list[tuple[int, str]]:
    """Top-level statements with the line each starts on.

    A statement ends at a line break outside any bracket or raw string; Rego has no
    other way to continue one.
    """
    statements: list[tuple[int, str]] = []
    buffer: list[str] = []
    start = 0
    depth = 0
    quote: str | None = None
    for number, line in enumerate(text.splitlines(), start=1):
        if not buffer and not line.strip():
            continue
        if not buffer:
            start = number
        buffer.append(line)
        change, quote = _depth_change(line, quote)
        depth += change
        if depth <= 0 and quote is None:
            statement = "\n".join(buffer).strip()
            if statement:
                statements.append((start, statement))
            buffer, depth = [], 0
    if buffer:
        statements.append((start, "\n".join(buffer).strip()))
    return statements


def split_body(body: str, separators: str = "\n;") -> list[str]:
    """A rule body's statements: one per line or ``;``, brackets kept together."""
    out: list[str] = []
    current: list[str] = []
    depth = 0
    quote: str | None = None
    escaped = False
    for ch in body:
        if quote:
            current.append(ch)
            if escaped:
                escaped = False
            elif ch == "\\" and quote == '"':
                escaped = True
            elif ch == quote:
                quote = None
            continue
        if ch in '"`':
            quote = ch
        elif ch in "{[(":
            depth += 1
        elif ch in "}])":
            depth -= 1
        if ch in separators and depth == 0:
            statement = "".join(current).strip()
            if statement:
                out.append(statement)
            current = []
            continue
        current.append(ch)
    tail = "".join(current).strip()
    if tail:
        out.append(tail)
    return out


def string_literal(text: str) -> str | None:
    """The value of a Rego string or raw string, or None if ``text`` is not one."""
    match = _STRING.match(text.strip())
    if not match:
        return None
    if match.group(2) is not None:
        return match.group(2)
    raw = match.group(1)
    try:
        return bytes(raw, "utf-8").decode("unicode_escape").encode("latin-1").decode("utf-8")
    except (UnicodeDecodeError, UnicodeEncodeError):
        return raw.replace('\\"', '"').replace("\\\\", "\\")


def string_collection(text: str) -> list[str] | None:
    """``{"a", "b"}`` or ``["a", "b"]`` (strings only) as a list, else None."""
    text = text.strip()
    if text in ("set()", "{}", "[]"):
        return []
    if len(text) < 2 or (text[0], text[-1]) not in (("{", "}"), ("[", "]")):
        return None
    inner = text[1:-1].strip()
    if not inner:
        return []
    values: list[str] = []
    for part in split_body(inner, separators=","):
        value = string_literal(part.strip())
        if value is None:
            return None
        values.append(value)
    return values


def constant_value(text: str) -> Any:
    """A literal string, number, boolean or string collection; None for anything else."""
    text = text.strip()
    collection = string_collection(text)
    if collection is not None:
        return collection
    literal = string_literal(text)
    if literal is not None:
        return literal
    if _NUMBER.match(text):
        return float(text) if "." in text else int(text)
    if text in ("true", "false"):
        return text == "true"
    return None


def parse_module(text: str, file: str = "") -> RegoModule:
    """Read one ``.rego`` file. Never raises: what it cannot read stays a statement."""
    module = RegoModule(package="", file=file)
    for line, statement in split_statements(strip_comments(text)):
        if statement.startswith("package "):
            module.package = statement.split(None, 1)[1].strip()
            continue
        if statement.startswith("import ") or statement.startswith("default "):
            module.statements.append(statement)
            continue
        rule = None
        for pattern in (_SET_RULE, _SET_RULE_LEGACY):
            match = pattern.match(statement)
            if match:
                rule = RegoRule(
                    name=match.group(1),
                    head=match.group(2).strip(),
                    body=split_body(match.group(3)),
                    line=line,
                    source=statement,
                    file=file,
                )
                break
        if rule is None and "{" not in statement.split(" if ", 1)[0]:
            match = _SET_RULE_ONE_LINE.match(statement)
            if match and "\n" not in match.group(3).strip():
                rule = RegoRule(
                    name=match.group(1),
                    head=match.group(2).strip(),
                    body=[match.group(3).strip()],
                    line=line,
                    source=statement,
                    file=file,
                )
        if rule is not None:
            module.rules.append(rule)
            continue
        helper = _HELPER.match(statement)
        if helper:
            module.helpers.setdefault(helper.group(1), []).append(split_body(helper.group(2)))
            module.statements.append(statement)
            continue
        assign = _ASSIGN.match(statement)
        if assign and " if " not in statement and not statement.rstrip().endswith("if"):
            value = constant_value(assign.group(2))
            if value is not None:
                module.constants[assign.group(1)] = value
                continue
        if assign and re.search(r"\binput\.(output|content|text)\b", statement):
            name = assign.group(1)
            if "output" in name or "text" in name or "content" in name:
                module.text_aliases.add(name)
        module.statements.append(statement)
    return module


def parse_bundle(files: dict[str, str]) -> list[RegoModule]:
    """Every ``.rego`` file in a bundle, test files left out."""
    modules: list[RegoModule] = []
    for name in sorted(files):
        if not name.endswith(".rego") or name.endswith("_test.rego"):
            continue
        modules.append(parse_module(files[name], file=name))
    return modules


__all__ = [
    "RegoModule",
    "RegoRule",
    "constant_value",
    "parse_bundle",
    "parse_module",
    "split_body",
    "split_statements",
    "string_collection",
    "string_literal",
    "strip_comments",
]
