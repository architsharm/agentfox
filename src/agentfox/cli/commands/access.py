"""`agentfox access` — declare which column decides whose row it is."""

from __future__ import annotations

import typer

from agentfox.cli.commands._shared import _session, console

access_app = typer.Typer(
    help="Declare which column decides whose row it is, so a query across every "
    "customer stops reading as ordinary.",
    no_args_is_help=True,
)


@access_app.command("declare-scope")
def access_declare_scope(
    table: str = typer.Argument(..., help="Table name"),
    column: str = typer.Option(..., "--column", help="Column that decides whose row it is"),
    principal_key: str = typer.Option(
        "id",
        "--principal-key",
        help="Attribute of the calling principal the column must equal",
    ),
    restricted_columns: str = typer.Option(
        "",
        "--restricted-columns",
        help="Comma-separated columns nobody should receive even for their own row",
    ),
) -> None:
    """P18 — declare which column on a table decides whose row it is, so
    `analyse_access()` can prove a query is scoped instead of assuming it. An
    undeclared table is reported, never assumed safe (see `data_access`'s own
    docstring).
    """
    from sqlalchemy import select

    from agentfox.core.models import AccessScopeRule

    restricted = [c.strip() for c in restricted_columns.split(",") if c.strip()]
    with _session() as session:
        rule = session.scalar(select(AccessScopeRule).where(AccessScopeRule.table_name == table))
        if rule is None:
            rule = AccessScopeRule(table_name=table)
            session.add(rule)
        rule.is_reference = False
        rule.column = column
        rule.principal_key = principal_key
        rule.restricted_columns = restricted

    suffix = f" (restricted: {', '.join(restricted)})" if restricted else ""
    console.print(f"[bold]{table}[/] scoped by {column} = principal.{principal_key}{suffix}")


@access_app.command("declare-reference")
def access_declare_reference(
    table: str = typer.Argument(
        ..., help="Table name — belongs to nobody (currencies, statuses, postcodes)"
    ),
) -> None:
    """P18 — declare a table that belongs to nobody, so `analyse_access()` does not
    flag it as an undeclared/unscoped table.
    """
    from sqlalchemy import select

    from agentfox.core.models import AccessScopeRule

    with _session() as session:
        rule = session.scalar(select(AccessScopeRule).where(AccessScopeRule.table_name == table))
        if rule is None:
            rule = AccessScopeRule(table_name=table, is_reference=True)
            session.add(rule)
        else:
            rule.is_reference = True

    console.print(f"[bold]{table}[/] declared as a reference table")
