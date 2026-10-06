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


@agents_app.command("register")
def agents_register(
    slug: str = typer.Argument(..., help="Agent slug, e.g. support-triage."),
    name: str | None = typer.Option(None, "--name", help="Display name. Default: the slug."),
    owner: str | None = typer.Option(
        None, "--owner", help="Owner's email. An agent with no owner is a finding."
    ),
    team: str | None = typer.Option(None, "--team", help="Owning team."),
    env: str | None = typer.Option(
        None, "--env", help="Environment it runs in. Default: production, or its current one."
    ),
    risk_tier: str | None = typer.Option(
        None,
        "--risk-tier",
        help="minimal | limited | high | prohibited. Default: limited, or its current one.",
    ),
) -> None:
    """Register an agent (or update one), so it is owned rather than shadow.

    Agents also appear on their first call; registering one up front gives it an
    owner and an environment before it has run, and turns a shadow agent into a
    registered one. Options left out keep the agent's current values.
    """
    from sqlalchemy import select

    from agentfox.core.models import Agent
    from agentfox.prove.audit import chain
    from agentfox.registry.service import register_agent

    tiers = ("minimal", "limited", "high", "prohibited")
    if risk_tier is not None and risk_tier not in tiers:
        console.print(f"[red]--risk-tier must be one of {', '.join(tiers)}[/]")
        raise typer.Exit(2)
    with _session() as session:
        existing = session.scalar(select(Agent).where(Agent.slug == slug))
        was_shadow = existing is not None and not existing.registered
        agent = register_agent(
            session,
            slug,
            name=name or "",
            owner_email=owner,
            owner_team=team,
            # register_agent overwrites these two every call; keep what is there
            # unless the operator said otherwise.
            environment=env or (existing.environment if existing else "production"),
            risk_tier=risk_tier or (existing.risk_tier if existing else "limited"),
        )
        chain.append(
            session,
            "agent.registered",
            actor_type="user",
            actor_id="cli",
            subject_type="agent",
            subject_id=agent.id,
            payload={
                "slug": agent.slug,
                "name": agent.name,
                "owner": agent.owner_email,
                "team": agent.owner_team,
                "environment": agent.environment,
                "risk_tier": agent.risk_tier,
                "created": existing is None,
            },
        )
        row = (agent.slug, agent.name, agent.owner_email, agent.environment, agent.risk_tier)
    verb = (
        "registered"
        if existing is None
        else "was shadow, now registered"
        if was_shadow
        else "updated"
    )
    console.print(f"[green]✓[/] [bold]{row[0]}[/] {verb}")
    console.print(
        f"  name {row[1]} · owner {row[2] or '[red]none[/]'} · env {row[3]} · risk {row[4]}"
    )
    if not row[2]:
        console.print("  [dim]no owner — set one with --owner, or it shows up as unowned.[/]")


@agents_app.command("budget")
def agents_budget(
    slug: str = typer.Argument(..., help="Agent slug."),
    max_calls: int | None = typer.Option(None, "--max-calls", help="Calls per window."),
    max_tokens: int | None = typer.Option(None, "--max-tokens", help="Tokens per window."),
    max_cost_usd: float | None = typer.Option(
        None, "--max-cost-usd", help="Spend per window, in USD."
    ),
    max_depth: int | None = typer.Option(
        None, "--max-depth", help="Longest tool-call chain in one run."
    ),
    window: str | None = typer.Option(None, "--window", help="minute | hour | day."),
    clear: bool = typer.Option(False, "--clear", help="Remove the agent's budget."),
) -> None:
    """Show or set an agent's budget: the caps `budget.exceeded` blocks on.

    With no option it prints the current caps and usage. Each option sets one cap and
    leaves the others as they are; 0 removes that cap. Over a cap, the agent's calls
    are blocked (`budget.exhausted`) until the window rolls over.
    """
    from sqlalchemy import select

    from agentfox.core.models import Agent, Budget
    from agentfox.prove.audit import chain
    from agentfox.runtime.reliability import WINDOWS

    if window is not None and window not in WINDOWS:
        console.print(f"[red]--window must be one of {', '.join(WINDOWS)}[/]")
        raise typer.Exit(2)
    for label, value in (
        ("--max-calls", max_calls),
        ("--max-tokens", max_tokens),
        ("--max-cost-usd", max_cost_usd),
        ("--max-depth", max_depth),
    ):
        if value is not None and value < 0:
            console.print(f"[red]{label} cannot be negative[/]")
            raise typer.Exit(2)
    changing = clear or any(
        v is not None for v in (max_calls, max_tokens, max_cost_usd, max_depth, window)
    )

    with _session() as session:
        agent = session.scalar(select(Agent).where(Agent.slug == slug))
        if agent is None:
            print_unknown_agent(console, session, slug)
            raise typer.Exit(1)
        budget = session.scalar(
            select(Budget).where(Budget.scope_type == "agent", Budget.scope_id == agent.id)
        )
        if clear:
            if budget is not None:
                session.delete(budget)
                chain.append(
                    session,
                    "budget.cleared",
                    actor_type="user",
                    actor_id="cli",
                    subject_type="agent",
                    subject_id=agent.id,
                    payload={"slug": slug},
                )
            console.print(f"[green]✓[/] {slug}: no budget")
            return
        if changing:
            if budget is None:
                budget = Budget(scope_type="agent", scope_id=agent.id)
                session.add(budget)
            before = {
                "max_calls": budget.max_calls,
                "max_tokens": budget.max_tokens,
                "max_cost_usd": budget.max_cost_usd,
                "max_depth": budget.max_depth,
                "window": budget.window,
            }
            if max_calls is not None:
                budget.max_calls = max_calls or None
            if max_tokens is not None:
                budget.max_tokens = max_tokens or None
            if max_cost_usd is not None:
                budget.max_cost_usd = max_cost_usd or None
            if max_depth is not None:
                budget.max_depth = max_depth or None
            if window is not None:
                budget.window = window
            budget.window = budget.window or "hour"
            session.flush()
            chain.append(
                session,
                "budget.set",
                actor_type="user",
                actor_id="cli",
                subject_type="agent",
                subject_id=agent.id,
                payload={
                    "slug": slug,
                    "before": before,
                    "after": {
                        "max_calls": budget.max_calls,
                        "max_tokens": budget.max_tokens,
                        "max_cost_usd": budget.max_cost_usd,
                        "max_depth": budget.max_depth,
                        "window": budget.window,
                    },
                },
            )
        if budget is None:
            console.print(
                f"[bold]{slug}[/]: no budget — set one with "
                f"`agentfox agents budget {slug} --max-calls N`."
            )
            return
        caps = (
            ("calls", budget.calls, budget.max_calls),
            ("tokens", budget.tokens, budget.max_tokens),
            ("cost USD", round(budget.cost_usd, 4), budget.max_cost_usd),
        )
        depth, per = budget.max_depth, budget.window
    console.print(f"[bold]{slug}[/] budget, per {per}" + (" [green](saved)[/]" if changing else ""))
    for label, used, cap in caps:
        console.print(f"  {label:<9} {used} / {cap if cap is not None else '[dim]no cap[/]'}")
    console.print(f"  {'depth':<9} {depth if depth is not None else '[dim]no cap[/]'}")


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
