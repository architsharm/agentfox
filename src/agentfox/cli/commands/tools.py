"""Declare what each tool can do, so containment can reason over it (`agentfox declare tool`)."""

from __future__ import annotations

import typer
from rich.table import Table

from agentfox.cli.commands._shared import _emit, _session, console

tools_app = typer.Typer(
    help="Declare what each tool can do, so containment has something to reason over.",
    no_args_is_help=True,
)


@tools_app.command("declare")
def tools_declare(
    key: str,
    impact: str = typer.Option(
        ...,
        "--impact",
        help=(
            "read | write | high_impact | irreversible — the axis every containment rule "
            "reasons over."
        ),
    ),
    name: str = typer.Option("", "--name"),
    description: str = typer.Option("", "--description"),
    triggers: str = typer.Option("", "--triggers", help="Comma-separated downstream effects."),
    output_trust: str | None = typer.Option(
        None,
        "--output-trust",
        help=(
            "untrusted | trusted — whether values copied out of this tool's output taint "
            "the arguments they land in. Default for a new tool: untrusted. Declare "
            "trusted only for a system of record you control, such as a CRM read."
        ),
    ),
) -> None:
    """Declare a tool and what it can do.

    Containment is declared, not detected: an irreversible tool recorded as `read` is one
    a tainted argument can reach. This is the command that makes least privilege real, and
    it is deliberately the first thing `agentfox init` points at.
    """
    from agentfox.core.models import OUTPUT_TRUST_LEVELS
    from agentfox.registry.service import upsert_tool

    valid = ("read", "write", "high_impact", "irreversible")
    if impact not in valid:
        console.print(f"[red]impact must be one of: {', '.join(valid)}[/]")
        raise typer.Exit(2)
    if output_trust is not None and output_trust not in OUTPUT_TRUST_LEVELS:
        console.print(f"[red]output trust must be one of: {', '.join(OUTPUT_TRUST_LEVELS)}[/]")
        raise typer.Exit(2)

    with _session() as session:
        tool = upsert_tool(
            session,
            key,
            name=name,
            impact=impact,
            description=description,
            output_trust=output_trust,
        )
        if triggers:
            tool.triggers_json = [t.strip() for t in triggers.split(",") if t.strip()]
        declared_triggers = list(tool.triggers_json or [])
        declared_trust = tool.output_trust

    console.print(f"[bold]{key}[/] declared — impact [bold]{impact}[/], output {declared_trust}")
    if declared_triggers:
        console.print(f"  triggers: {', '.join(declared_triggers)}")
    if declared_trust == "trusted":
        console.print(
            "  [dim]values an agent copies out of this tool's output no longer count as "
            "untrusted input, and no longer raise the run's provenance[/]"
        )
    if impact in ("high_impact", "irreversible"):
        console.print(
            "  [dim]arguments carrying untrusted provenance now require approval or are "
            "refused, whether or not a detector fires[/]"
        )


@tools_app.command("list")
def tools_list(as_json: bool = typer.Option(False, "--json")) -> None:
    """Every declared tool and what it is allowed to do."""
    from sqlalchemy import select

    from agentfox.core.models import Tool
    from agentfox.registry.service import impact_source_of

    with _session() as session:
        tools = list(session.scalars(select(Tool).order_by(Tool.key)))
        rows = [
            {
                "key": t.key,
                "impact": t.impact,
                "impact_source": impact_source_of(t),
                "triggers": list(t.triggers_json or []),
                "output_trust": t.output_trust or "untrusted",
                "description": t.description,
            }
            for t in tools
        ]

    if as_json:
        _emit(rows, True)
        return
    if not rows:
        console.print("[yellow]no tools declared[/] — `agentfox declare tool <key> --impact ...`")
        return
    table = Table(box=None, padding=(0, 2))
    table.add_column("tool")
    table.add_column("impact")
    table.add_column("output")
    table.add_column("triggers")
    for row in rows:
        colour = {"irreversible": "red", "high_impact": "yellow", "write": "cyan"}.get(
            row["impact"], "dim"
        )
        # An inferred impact is a guess from the tool's name; say so next to it, so
        # nobody reads `read` on an unconfirmed tool as a decision someone made.
        impact = f"[{colour}]{row['impact']}[/]"
        if row["impact_source"] == "inferred":
            impact += " [dim](inferred — confirm with `agentfox declare tool`)[/]"
        trust = "[green]trusted[/]" if row["output_trust"] == "trusted" else "[dim]untrusted[/]"
        table.add_row(row["key"], impact, trust, ", ".join(row["triggers"]) or "—")
    console.print(table)


@tools_app.command("set-triggers")
def tools_set_triggers(
    key: str = typer.Argument(..., help="Tool key, e.g. demo.delete_user"),
    triggers: str = typer.Option(
        "", "--triggers", help="Comma-separated tool keys this call sets off downstream"
    ),
) -> None:
    """Declare what a tool call sets off downstream (a DB trigger, a webhook, a
    fan-out), so `cascade_risk()` can actually see it. An undeclared trigger stays
    invisible by design (see `effects.cascade_risk`'s own docstring) — this is how
    an operator closes that gap for one tool.
    """
    from sqlalchemy import select

    from agentfox.core.models import Tool

    declared = [t.strip() for t in triggers.split(",") if t.strip()]
    with _session() as session:
        tool = session.scalar(select(Tool).where(Tool.key == key))
        if tool is None:
            console.print(
                f"[red]unknown tool '{key}' — register it first "
                "(agentfox scan mcp, or via seed data)[/]"
            )
            raise typer.Exit(1)
        tool.triggers_json = declared

    console.print(f"[bold]{key}[/] triggers: {', '.join(declared) or '(none)'}")
