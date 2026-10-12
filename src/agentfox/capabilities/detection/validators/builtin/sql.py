"""Validators: sql. See `validators/builtin/__init__.py`.

SQL read with sqlglot (parsed, never run): whether it parses, whether it uses a
construct a workspace forbids (a DROP, a DELETE without care), and whether it only
touches columns it is allowed to. A tool call's arguments arrive as JSON, so on
that surface each string argument that reads as SQL is checked.
"""

from __future__ import annotations

import json
from functools import cache
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from agentfox.capabilities.detection.validators import register_validator
from agentfox.capabilities.detection.validators.base import (
    CheckContext,
    Finding,
    Validator,
    span_finding,
)

#: Root expression types that are statements. sqlglot is lenient: "hello world"
#: parses as a column with an alias, which is no query.
_STATEMENT_TYPES = (
    "Query",
    "Insert",
    "Update",
    "Delete",
    "Merge",
    "Create",
    "Drop",
    "Alter",
    "Command",
    "Use",
    "Set",
    "Transaction",
    "Commit",
    "Rollback",
    "Describe",
    "Pragma",
    "Grant",
    "Revoke",
    "Analyze",
    "Copy",
    "TruncateTable",
    "Show",
    "Kill",
    "Cache",
    "Uncache",
    "Refresh",
    "LoadData",
    "Comment",
    "Execute",
    "Summarize",
    "Declare",
    "Values",
)


@cache
def _statement_types() -> tuple[type, ...]:
    from sqlglot import exp

    found = (getattr(exp, n, None) for n in _STATEMENT_TYPES)
    return tuple(t for t in found if isinstance(t, type))


def _string_leaves(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in _string_leaves(v)]
    if isinstance(value, list):
        return [s for v in value for s in _string_leaves(v)]
    return []


def _candidates(text: str, ctx: CheckContext) -> list[str]:
    """The SQL to read: the text, or on a tool call each string argument."""
    if ctx.surface in ("tool_args", "tool_result"):
        try:
            value = json.loads(text)
        except ValueError:
            return [text]
        if isinstance(value, dict | list):
            return _string_leaves(value)
    return [text]


def _parse(sql: str, dialect: str | None) -> list[Any] | None:
    """Parsed statements, or None when the text does not parse."""
    import sqlglot
    from sqlglot.errors import ParseError, TokenError

    try:
        return [e for e in sqlglot.parse(sql, read=dialect or None) if e is not None]
    except (ParseError, TokenError):
        return None


class _DialectParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: A sqlglot dialect ("postgres", "mysql", "sqlite", …); empty is generic SQL.
    dialect: str | None = Field(None, max_length=40)

    @field_validator("dialect")
    @classmethod
    def _known(cls, value: str | None) -> str | None:
        if not value:
            return None
        try:
            from sqlglot.dialects.dialect import Dialect
        except ImportError:  # validated again when the validator becomes available
            return value
        try:
            Dialect.get_or_raise(value)
        except ValueError:
            raise ValueError(f"unknown SQL dialect {value!r}") from None
        return value


class ValidSqlParams(_DialectParams):
    pass


@register_validator
class ValidSql(Validator):
    """Adapted from guardrails-ai/valid_sql (Apache-2.0).

    Upstream checked syntax with `sqlvalidator` or a live database connection; this
    parses with sqlglot, offline, in an optional dialect.
    """

    name = "valid_sql"
    label = "Valid SQL"
    description = "The text must parse as one or more SQL statements."
    entity_type = "CODE.SQL_SYNTAX"
    surfaces = ("output", "tool_args")
    Params = ValidSqlParams
    requires = ("sqlglot",)
    upstream = "guardrails-ai/valid_sql"
    scan_views = False

    def check(self, text: str, params: ValidSqlParams, ctx: CheckContext) -> list[Finding]:
        import sqlglot
        from sqlglot.errors import ParseError, TokenError

        try:
            statements = [
                e for e in sqlglot.parse(text, read=params.dialect or None) if e is not None
            ]
        except ParseError as exc:
            err = exc.errors[0] if exc.errors else {}
            reason = f"SQL syntax error: {err.get('description') or 'cannot parse'}"
            line, col = err.get("line"), err.get("col")
            if line and col:
                # sqlglot's column is 1-based and points at the end of the bad token.
                lines = text.split("\n")
                start = sum(len(x) + 1 for x in lines[: line - 1])
                token = err.get("highlight") or ""
                end = start + col
                begin = max(start, end - len(token)) if token else max(start, end - 1)
                return [span_finding(text, begin, end, reason, line=line, col=col)]
            return [Finding(reason=reason)]
        except TokenError as exc:
            return [Finding(reason=f"SQL syntax error: {exc}")]
        if not statements:
            return [Finding(reason="no SQL statement")]
        kinds = _statement_types()
        for stmt in statements:
            if not isinstance(stmt, kinds):
                return [Finding(reason="not a SQL statement")]
        return []


class ExcludeSqlPredicatesParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: sqlglot expression names that must not appear: "Drop", "Delete", "Where", …
    predicates: list[str] = Field(min_length=1, max_length=100)

    @field_validator("predicates")
    @classmethod
    def _exist(cls, value: list[str]) -> list[str]:
        try:
            from sqlglot import exp
        except ImportError:  # checked again at run time
            return value
        for pred in value:
            node = getattr(exp, pred, None)
            if not (isinstance(node, type) and issubclass(node, exp.Expression)):
                raise ValueError(f"predicate {pred!r} does not exist")
        return value


@register_validator
class ExcludeSqlPredicates(Validator):
    """Adapted from guardrails-ai/exclude_sql_predicates (Apache-2.0)."""

    name = "exclude_sql_predicates"
    label = "Forbidden SQL constructs"
    description = (
        "SQL must not use any of the listed constructs (sqlglot names such as Drop, "
        "Delete, Update, Where)."
    )
    entity_type = "ACTION.SQL_PREDICATE"
    surfaces = ("tool_args", "output")
    Params = ExcludeSqlPredicatesParams
    requires = ("sqlglot",)
    upstream = "guardrails-ai/exclude_sql_predicates"

    def check(
        self, text: str, params: ExcludeSqlPredicatesParams, ctx: CheckContext
    ) -> list[Finding]:
        from sqlglot import exp

        found: list[str] = []
        for sql in _candidates(text, ctx):
            # Text that does not parse holds none of the constructs as far as we can
            # tell (upstream raised); `valid_sql` is the check for syntax.
            statements = _parse(sql, None) or []
            for stmt in statements:
                for pred in params.predicates:
                    node = getattr(exp, pred, None)
                    if node is None:
                        raise ValueError(f"predicate {pred!r} does not exist")
                    if pred not in found and stmt.find(node) is not None:
                        found.append(pred)
        return [
            Finding(
                reason=f"SQL contains the forbidden construct {pred}", detail={"predicate": pred}
            )
            for pred in found
        ]


class SqlColumnPresenceParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: Columns the SQL may use.
    cols: list[str] = Field(min_length=1, max_length=2000)


@register_validator
class SqlColumnPresence(Validator):
    """Adapted from guardrails-ai/sql_column_presence_validator (Apache-2.0)."""

    name = "sql_column_presence"
    label = "SQL uses only known columns"
    description = "SQL must only reference columns from a given list."
    entity_type = "SCHEMA.SQL_COLUMN"
    surfaces = ("tool_args", "output")
    Params = SqlColumnPresenceParams
    requires = ("sqlglot",)
    upstream = "guardrails-ai/sql_column_presence_validator"
    scan_views = False

    def check(self, text: str, params: SqlColumnPresenceParams, ctx: CheckContext) -> list[Finding]:
        from sqlglot import exp

        allowed = set(params.cols)
        used: set[str] = set()
        for sql in _candidates(text, ctx):
            for stmt in _parse(sql, None) or []:
                for col in stmt.find_all(exp.Column):
                    used.add(col.alias_or_name)
        unknown = sorted(used - allowed)
        if not unknown:
            return []
        return [
            Finding(
                reason=f"SQL uses columns not in the allowed list: {', '.join(unknown)}",
                detail={"columns": unknown},
            )
        ]
