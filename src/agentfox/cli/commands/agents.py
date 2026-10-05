"""`agentfox agents` — find every running agent, who owns it, and stop it."""

from __future__ import annotations

import typer
from rich.table import Table

from agentfox.cli._style import print_unknown_agent
from agentfox.cli.commands._shared import _emit, _session, console

agents_app = typer.Typer(
    help="Find every agent that is running, and who owns it.",
    no_args_is_help=True,
)


@agents_app.command("list")
def agents_list(
    as_json: bool = typer.Option(False, "--json"),
    stopped: bool = typer.Option(
        False, "--stopped", help="Only agents that are quarantined or killed, and why."
    ),
) -> None:
    """List every agent, registered or shadow."""
    if stopped:
        agents_controls()
        return
    from sqlalchemy import select

    from agentfox.core.models import Agent
    from agentfox.registry.service import inventory

    with _session() as session:
        agents = list(session.scalars(select(Agent).order_by(Agent.slug)))
        summary = inventory(session)
        rows = [
            {
                "slug": a.slug,
                "environment": a.environment,
                "risk_tier": a.risk_tier,
                "registered": a.registered,
                "owner": a.owner_email,
                "framework": a.framework,
            }
            for a in agents
        ]
    if as_json:
        _emit({"agents": rows, "inventory": summary}, True)
        return
    table = Table(box=None, pad_edge=False)
    for column in ("agent", "env", "risk", "registered", "owner", "framework"):
        table.add_column(column, style="bold" if column == "agent" else None)
    for row in rows:
        table.add_row(
            row["slug"],
            row["environment"],
            row["risk_tier"],
            "[green]yes[/]" if row["registered"] else "[red]SHADOW[/]",
            row["owner"] or "[red]unowned[/]",
            row["framework"] or "—",
        )
    console.print(table)
    console.print(
        f"  [dim]{summary['agents']} agents · {summary['shadow']} shadow · "
        f"{summary['unowned']} unowned · {summary['lineage_edges']} lineage edges[/]"
    )


@agents_app.command("discover")
def agents_discover() -> None:
    """Sweep for shadow agents, unowned agents, registry drift, identity posture and
    delegation cycles/depth."""
    from agentfox.identity import assess_posture
    from agentfox.registry.service import (
        assess_delegation,
        attest_registry,
        derive_lineage,
        detect_shadow_agents,
        unowned_agents,
    )

    with _session() as session:
        edges = derive_lineage(session)
        shadows = detect_shadow_agents(session)
        unowned = unowned_agents(session)
        drift = attest_registry(session)
        posture = assess_posture(session)
        delegation = assess_delegation(session)
    console.print(f"  lineage edges derived   {edges}")
    console.print(f"  shadow agents           [red]{len(shadows)}[/]")
    console.print(f"  unowned agents          [yellow]{len(unowned)}[/]")
    console.print(f"  registry drift findings [yellow]{len(drift)}[/]")
    console.print(f"  identity posture issues [yellow]{len(posture)}[/]")
    console.print(f"  delegation findings     [yellow]{len(delegation)}[/]")
    for shadow in shadows:
        console.print(
            f"    [red]shadow[/] {shadow['slug']} — {shadow['calls']} calls "
            f"in {shadow['environment']}"
        )


@agents_app.command("lineage")
def agents_lineage(slug: str, depth: int = 2) -> None:
    """Show what an agent reaches — the blast radius."""
    from agentfox.registry.service import derive_lineage, lineage

    with _session() as session:
        derive_lineage(session, slug)
        graph = lineage(session, slug, depth)
    console.print(f"[bold]{slug}[/] — blast radius {graph['blast_radius']}")
    for link in graph["links"]:
        console.print(
            f"  {link['source']} [dim]--{link['relation']}-->[/] {link['target']} "
            f"[dim](observed {link['observed_count']}×)[/]"
        )


@agents_app.command("quarantine")
def agents_quarantine(slug: str, reason: str = typer.Option("", "--reason", "-r")) -> None:
    """Stop an agent while you investigate. Reversible and audited."""
    _agent_state(slug, "quarantined", reason)


@agents_app.command("kill")
def agents_kill(slug: str, reason: str = typer.Option("", "--reason", "-r")) -> None:
    """Stop an agent now."""
    _agent_state(slug, "killed", reason)


@agents_app.command("resume")
def agents_resume(slug: str, reason: str = typer.Option("", "--reason", "-r")) -> None:
    """Restart a stopped agent."""
    _agent_state(slug, "active", reason)


@agents_app.command("controls")
def agents_controls() -> None:
    """Show every agent that is not in the active state."""
    from agentfox.registry.control import all_controls

    with _session() as session:
        rows = all_controls(session)
    if not rows:
        console.print("[green]all agents active[/]")
        return
    table = Table(box=None, pad_edge=False)
    for column in ("agent", "state", "reason", "by", "when"):
        table.add_column(column, style="bold" if column == "agent" else None)
    for row in rows:
        colour = {"killed": "red", "quarantined": "yellow"}.get(row["state"], "green")
        table.add_row(
            row["agent"],
            f"[{colour}]{row['state']}[/]",
            row["reason"] or "—",
            row["actor"] or "—",
            (row["changed_at"] or "")[:19],
        )
    console.print(table)


def _agent_state(slug: str, state: str, reason: str) -> None:
    from agentfox.registry.control import UnknownAgent, set_state

    with _session() as session:
        try:
            control = set_state(session, slug, state, reason=reason, actor="cli")
        except UnknownAgent as exc:
            print_unknown_agent(console, session, slug)
            raise typer.Exit(1) from exc
        previous, now = control.previous_state, control.state
    colour = {"killed": "red", "quarantined": "yellow"}.get(now, "green")
    console.print(
        f"[bold]{slug}[/] {previous or 'active'} → [{colour}]{now}[/]"
        + (f"  [dim]{reason}[/]" if reason else "")
    )
