"""How a tool actually reaches the database.

Two controls already sit near this and neither one answers the question. Capability
scoping asks whether the agent may call `db.query`. Action analysis asks whether the
statement is destructive. Both pass, cleanly, on::

    SELECT * FROM orders

run by a support agent acting for one customer. Nothing is destructive, the tool was
granted, the arguments are untainted — and the result is every customer's orders.

That is the gap. Authorisation is enforced on the *call*; the data boundary is enforced,
if at all, by a `WHERE` clause the model wrote. A guardrail that governs which tools an
agent may use, and never checks what those tools were pointed at, is protecting the
door and leaving the wall out.

So this proves the query is scoped, rather than assuming it. Given a declaration of
which tables carry whose data — `orders.customer_id` belongs to the customer — every
select is checked for a predicate binding that column to the *calling principal*.

The check that matters most is not the missing `WHERE`; it is the one that is present
and wrong::

    SELECT * FROM orders WHERE customer_id = 'C-4471'

That has a scope predicate. It passes every "is the query filtered" test anyone writes.
It is also horizontal privilege escalation whenever `C-4471` is not the caller, and a
model asked to look up "the customer's orders" will cheerfully put an id there that it
read out of a document, a previous turn, or an injected instruction. The binding has to
be to the principal — a placeholder the runtime fills, or the principal's own value —
and a literal the model chose is the finding even when it happens to be correct, because
next time it will not be.

Fail closed on unparseable, for the same reason action analysis does: a statement we
cannot read is a statement we cannot prove is scoped.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agentfox.capabilities.detection.actions import SQLGLOT_AVAILABLE, exp, sqlglot
from agentfox.core.finding import RiskFinding

# --- Declaration -----------------------------------------------------------


@dataclass(frozen=True)
class ScopeRule:
    """Which column on a table decides whose row it is."""

    table: str
    column: str
    #: The attribute of the calling principal the column must equal. Named rather than
    #: assumed so that `orders.customer_id = principal.customer_id` and
    #: `tickets.owner_id = principal.user_id` can both be expressed.
    principal_key: str = "id"
    #: Columns nobody should receive through this tool even when the row is theirs.
    restricted_columns: tuple[str, ...] = ()

    @property
    def key(self) -> str:
        return self.table.lower()


@dataclass(frozen=True)
class ReferenceTable:
    """A table that belongs to nobody: currencies, statuses, postcodes.

    Declared explicitly rather than inferred from the absence of a rule. An
    undeclared table is an unreviewed table, and treating "no rule" as "safe" is how a
    new table joins the schema and quietly becomes readable by everyone.
    """

    table: str

    @property
    def key(self) -> str:
        return self.table.lower()


# --- Findings --------------------------------------------------------------


AccessFinding = RiskFinding


@dataclass
class AccessAnalysis:
    """Whether a statement can be shown to touch only the caller's rows."""

    parsed: bool
    tables: list[str] = field(default_factory=list)
    scoped: list[str] = field(default_factory=list)
    unscoped: list[str] = field(default_factory=list)
    undeclared: list[str] = field(default_factory=list)
    findings: list[AccessFinding] = field(default_factory=list)
    parse_error: str | None = None

    @property
    def proven(self) -> bool:
        """True only when every table in the statement was shown to be safe.

        Deliberately not "no critical findings". The claim this makes is positive — the
        query is scoped — and an absence of evidence does not establish it.
        """
        return self.parsed and not self.findings

    @property
    def verdict(self) -> str:
        severities = {f.severity for f in self.findings}
        if "critical" in severities:
            return "block"
        if severities:
            return "escalate"
        return "allow"

    def to_json(self) -> dict[str, Any]:
        return {
            "parsed": self.parsed,
            "proven": self.proven,
            "verdict": self.verdict,
            "tables": self.tables,
            "scoped": self.scoped,
            "unscoped": self.unscoped,
            "undeclared": self.undeclared,
            "parse_error": self.parse_error,
            "findings": [f.to_json() for f in self.findings],
        }


# --- Analysis --------------------------------------------------------------


def _conjuncts(node: Any) -> list[Any]:
    """Flatten a WHERE into the predicates that actually constrain every row.

    Only the AND spine counts. ``customer_id = :me OR 1=1`` contains a perfectly good
    scope predicate and constrains nothing, so anything beneath an OR is excluded here
    rather than credited.
    """
    if node is None:
        return []
    if isinstance(node, exp.And):
        return _conjuncts(node.left) + _conjuncts(node.right)
    if isinstance(node, exp.Paren):
        return _conjuncts(node.this)
    return [node]


def _binds_to_principal(value: Any, principal: dict[str, Any], key: str) -> tuple[bool, str]:
    """Is the right-hand side of a scope predicate the caller, or something the model
    decided? Returns (bound, how)."""
    if isinstance(value, exp.Placeholder):
        return True, "placeholder"
    if isinstance(value, exp.Parameter):
        return True, "parameter"
    if isinstance(value, exp.Literal):
        expected = principal.get(key)
        if expected is not None and str(value.this) == str(expected):
            # Correct today, and only by coincidence: the runtime did not put it there.
            return True, "literal-matching-principal"
        return False, "literal"
    if isinstance(value, exp.Column):
        # A column comparison scopes to another row, not to the caller.
        return False, "column"
    return False, type(value).__name__.lower()


def _tables_in(select: Any) -> list[tuple[str, str]]:
    """(table name, alias-or-name) for everything this select reads from."""
    out: list[tuple[str, str]] = []
    for source in select.find_all(exp.Table):
        # Skip tables belonging to a nested select; those are handled on their own pass.
        if source.find_ancestor(exp.Select) is not select:
            continue
        name = source.name
        if not name:
            continue
        out.append((name.lower(), (source.alias or name).lower()))
    return out


def analyse_access(
    statement: str,
    *,
    principal: dict[str, Any] | None = None,
    rules: list[ScopeRule] | None = None,
    reference: list[ReferenceTable] | None = None,
    dialect: str = "postgres",
    strictness: str = "standard",
) -> AccessAnalysis:
    """Prove that a statement can only return the caller's rows.

    ``principal`` is what the runtime knows about who is asking — ``{"customer_id":
    "C-1"}`` — and is used to tell a bound scope from one the model wrote out. Passing
    no principal is allowed and makes every literal binding a finding, which is the
    right default: without knowing who is asking, no literal can be shown to be them.

    ``strictness="strict"`` promotes ``undeclared-table`` from ``"high"`` (escalate)
    to ``"critical"`` (block) — the standard default treats an unreviewed table as
    something a human should look at, not something to refuse outright, since a
    schema legitimately grows faster than anyone declares scope rules for it. A
    deployment that wants "no undeclared table is ever queried, period" opts into
    that outright.
    """
    principal = principal or {}
    undeclared_severity = "critical" if strictness == "strict" else "high"
    by_table = {r.key: r for r in (rules or [])}
    reference_tables = {r.key for r in (reference or [])}

    if not SQLGLOT_AVAILABLE:  # pragma: no cover - exercised only without the extra
        return AccessAnalysis(
            parsed=False,
            parse_error="sqlglot is not installed, so access scoping cannot be proven",
            findings=[
                AccessFinding(
                    "unprovable",
                    "the SQL parser is unavailable; scoping cannot be "
                    "established and the statement is refused",
                    "critical",
                )
            ],
        )

    try:
        tree = sqlglot.parse_one(statement, read=dialect)
    except Exception as exc:
        return AccessAnalysis(
            parsed=False,
            parse_error=str(exc),
            findings=[
                AccessFinding(
                    "unparseable",
                    f"the statement could not be parsed, so it cannot be shown to be scoped: {exc}",
                    "critical",
                )
            ],
        )
    if tree is None:
        return AccessAnalysis(
            parsed=False,
            parse_error="empty statement",
            findings=[AccessFinding("unparseable", "empty statement", "critical")],
        )

    analysis = AccessAnalysis(parsed=True)
    seen: set[str] = set()

    for select in tree.find_all(exp.Select):
        where = select.args.get("where")
        predicates = _conjuncts(where.this if where else None)
        # Predicates that were written but sit under an OR, for a better message.
        defeated = [
            node
            for node in (where.find_all(exp.EQ) if where else [])
            if node.find_ancestor(exp.Or) is not None
        ]

        for table, alias in _tables_in(select):
            if table not in seen:
                seen.add(table)
                analysis.tables.append(table)

            if table in reference_tables:
                continue

            rule = by_table.get(table)
            if rule is None:
                if table not in analysis.undeclared:
                    analysis.undeclared.append(table)
                    analysis.findings.append(
                        AccessFinding(
                            "undeclared-table",
                            f"'{table}' has no scope rule and is not declared as a "
                            "reference table, so there is nothing to check it against",
                            undeclared_severity,
                            {"table": table},
                        )
                    )
                continue

            bound = False
            how = ""
            for predicate in predicates:
                if not isinstance(predicate, (exp.EQ, exp.In)):
                    continue
                column = predicate.this if isinstance(predicate.this, exp.Column) else None
                if column is None or column.name.lower() != rule.column.lower():
                    continue
                if column.table and column.table.lower() not in (alias, table):
                    continue
                value = (
                    predicate.expression
                    if isinstance(predicate, exp.EQ)
                    else next(iter(predicate.expressions), None)
                )
                bound, how = _binds_to_principal(value, principal, rule.principal_key)
                if bound:
                    break

            if bound:
                if table not in analysis.scoped:
                    analysis.scoped.append(table)
                if how == "literal-matching-principal":
                    analysis.findings.append(
                        AccessFinding(
                            "scope-literal-not-bound",
                            f"'{table}.{rule.column}' is compared to a literal that happens "
                            "to be the caller. It is correct this time by coincidence — the "
                            "runtime did not put it there, and the model that chose it can "
                            "choose differently on the next turn",
                            "high",
                            {"table": table, "column": rule.column},
                        )
                    )
                continue

            if table not in analysis.unscoped:
                analysis.unscoped.append(table)

            if any(
                isinstance(node, exp.EQ)
                and isinstance(node.this, exp.Column)
                and node.this.name.lower() == rule.column.lower()
                for node in defeated
            ):
                analysis.findings.append(
                    AccessFinding(
                        "scope-defeated-by-or",
                        f"'{table}' has a scope predicate on {rule.column}, but it sits "
                        "under an OR and therefore constrains nothing",
                        "critical",
                        {"table": table, "column": rule.column},
                    )
                )
            elif how == "literal":
                analysis.findings.append(
                    AccessFinding(
                        "scope-bound-to-literal",
                        f"'{table}.{rule.column}' is bound to a value the model supplied "
                        "rather than to the caller. This is horizontal privilege "
                        "escalation: the id may have come from a document, an earlier turn "
                        "or an injected instruction",
                        "critical",
                        {"table": table, "column": rule.column},
                    )
                )
            else:
                aggregate = any(select.find_all(exp.AggFunc))
                analysis.findings.append(
                    AccessFinding(
                        "unscoped-table",
                        f"'{table}' carries per-{rule.principal_key} rows and this "
                        + (
                            "aggregate runs across every one of them"
                            if aggregate
                            else "query has no predicate binding it to the caller"
                        ),
                        "critical",
                        {"table": table, "column": rule.column, "aggregate": aggregate},
                    )
                )

        # Restricted columns are checked only where the row itself is permitted.
        for table, _alias in _tables_in(select):
            rule = by_table.get(table)
            if not rule or not rule.restricted_columns:
                continue
            restricted = {c.lower() for c in rule.restricted_columns}
            selected = {c.name.lower() for c in select.expressions if isinstance(c, exp.Column)}
            if any(isinstance(e, exp.Star) for e in select.expressions):
                analysis.findings.append(
                    AccessFinding(
                        "select-star-over-restricted",
                        f"'SELECT *' on '{table}' returns {sorted(restricted)}, which this "
                        "tool is not entitled to disclose even for the caller's own row",
                        "high",
                        {"table": table, "restricted": sorted(restricted)},
                    )
                )
            elif hit := sorted(selected & restricted):
                analysis.findings.append(
                    AccessFinding(
                        "restricted-column",
                        f"'{table}' column(s) {hit} are withheld from this tool",
                        "high",
                        {"table": table, "columns": hit},
                    )
                )

    return analysis


# --- Connection identity ---------------------------------------------------

#: Roles that can read or change anything. A tool holding one of these has no data
#: boundary below the application layer, so every guarantee rests on the query text.
SUPERUSER_ROLES = ("postgres", "root", "admin", "sa", "superuser", "owner", "rds_superuser")


def connection_risk(
    role: str, *, operation: str = "read", environment: str = "production"
) -> AccessFinding | None:
    """Whether the credential the tool connects with leaves any floor under a mistake.

    Query-level scoping is a control on what the agent *asks for*. The connection role
    is the control on what it is *able* to get, and the two fail independently: a
    perfect scope predicate on a superuser connection is one prompt injection away from
    irrelevant, and a locked-down role turns the same injection into a permission error.
    """
    if role.lower() in SUPERUSER_ROLES:
        return AccessFinding(
            "superuser-connection",
            f"the tool connects as '{role}', which can read and change anything. "
            "Row-level scoping in the query is then the only boundary, and it is "
            "written by the model",
            "critical" if environment in ("production", "prod") else "high",
            {"role": role, "operation": operation, "environment": environment},
        )
    return None
