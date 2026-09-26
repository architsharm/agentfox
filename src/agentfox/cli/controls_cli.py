"""Command-line access to the controls that prevent business failures.

The audit's usability finding was that the trivial things observe and the protective
things are expert-only: answerability was REST-only, provenance was Python-only, and
escalation needed the host application to push conversation turns. All three were
complete engines nobody outside this repository could switch on.

These commands exist so that declaring a knowledge boundary or tiering a corpus is the
same kind of act as running `agentfox check` — one line, no client library, no reading
the PRD first.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ._style import print_unknown_agent

console = Console()


def _session():
    """A session on an initialised database. `init_db` is idempotent, and without it
    a command run before `agentfox init` dies on "no such table"."""
    from ..db import init_db, session_scope

    init_db()
    return session_scope()

TIER_COLOUR = {
    "system_of_record": "green",
    "approved": "cyan",
    "unverified": "yellow",
    "external": "red",
}


# ---------------------------------------------------------------------------
# P7 — answerability
# ---------------------------------------------------------------------------


def boundary_set(
    agent: str = typer.Argument(..., help="Agent slug."),
    systems: str = typer.Option("", "--systems", help="Comma-separated systems of record."),
    months: int | None = typer.Option(None, "--coverage-months", help="Rolling window."),
    answerable: str = typer.Option(
        "fact,aggregate,procedure", "--answerable", help="Question types this agent may answer."
    ),
    out_of_scope: str = typer.Option("", "--out-of-scope", help="Comma-separated topics."),
    mode: str = typer.Option("observe", "--mode", help="observe | enforce"),
) -> None:
    """Declare what an agent is allowed to answer from (P7).

    Until this exists nothing stops the agent inventing an answer to a question it has
    no data for, which is the single failure most likely to reach a customer.
    """
    from sqlalchemy import select

    from ..answerability import QUESTION_TYPES, declare_boundary
    from ..models import Agent

    types = [t.strip() for t in answerable.split(",") if t.strip()]
    unknown = set(types) - set(QUESTION_TYPES)
    if unknown:
        console.print(f"[red]unknown question type(s): {sorted(unknown)}[/]")
        console.print(f"[dim]choose from: {', '.join(QUESTION_TYPES)}[/]")
        raise typer.Exit(1)

    with _session() as session:
        record = session.scalar(select(Agent).where(Agent.slug == agent))
        if record is None:
            print_unknown_agent(console, session, agent)
            raise typer.Exit(1)
        declare_boundary(
            session,
            agent_id=record.id,
            systems_of_record=[s.strip() for s in systems.split(",") if s.strip()],
            coverage_months=months,
            answerable_types=types,
            out_of_scope_topics=[t.strip() for t in out_of_scope.split(",") if t.strip()],
            mode=mode,
        )

    console.print(f"[green]✓[/] boundary declared for [bold]{agent}[/]")
    console.print(f"  answerable: {', '.join(types)}")
    if months:
        console.print(f"  coverage:   last {months} months")
    if mode == "observe":
        console.print(
            "  [dim]observe mode — refusals are recorded, not applied. "
            "Re-run with --mode enforce when the dry runs look right.[/]"
        )


def boundary_check(
    agent: str = typer.Argument(..., help="Agent slug."),
    question: str = typer.Argument(..., help="A question to test."),
) -> None:
    """Would this question be refused, and what would we say instead?

    Changes nothing, so it is safe to replay real traffic through before enforcing —
    which matters more here than anywhere else, because the false positives of this
    control are refusals shown to customers.
    """
    from sqlalchemy import select

    from ..answerability import classify_answerability, get_boundary
    from ..models import Agent

    with _session() as session:
        record = session.scalar(select(Agent).where(Agent.slug == agent))
        if record is None:
            print_unknown_agent(console, session, agent)
            raise typer.Exit(1)
        boundary = get_boundary(session, record.id)
        verdict = classify_answerability(question, boundary)

    if boundary is None:
        console.print("[yellow]no boundary declared — nothing would be refused[/]")
        console.print("[dim]declare one with `agentfox boundary set`[/]")
        return
    if verdict.answerable:
        console.print(f"[green]answerable[/]  [dim]({verdict.question_type})[/]")
        return
    console.print(
        Panel(
            verdict.response,
            title=f"[bold]would abstain — {verdict.abstention_kind}[/]",
            title_align="left",
            border_style="yellow" if verdict.mode == "observe" else "red",
        )
    )
    console.print(
        f"  [dim]{'recorded only (observe mode)' if not verdict.should_abstain else 'enforced'}[/]"
    )


# ---------------------------------------------------------------------------
# P8 — source authority
# ---------------------------------------------------------------------------


def sources_add(
    key: str = typer.Argument(..., help="Identifier the retriever emits."),
    tier: str = typer.Option("unverified", "--tier", "-t"),
    owner: str | None = typer.Option(None, "--owner"),
    domain: str | None = typer.Option(None, "--domain"),
    sla_hours: int | None = typer.Option(None, "--sla-hours", help="Freshness SLA."),
    updated: str | None = typer.Option(
        None, "--updated", help="When the source last changed (ISO, or 'now')."
    ),
    title: str = typer.Option("", "--title"),
) -> None:
    """Register a source and its authority tier (P8)."""
    from ..models import utcnow
    from ..provenance import TIERS, register_source

    if tier not in TIERS:
        console.print(f"[red]tier must be one of: {', '.join(TIERS)}[/]")
        raise typer.Exit(1)

    updated_at = None
    if updated:
        if updated.lower() == "now":
            updated_at = utcnow()
        else:
            try:
                updated_at = dt.datetime.fromisoformat(updated)
            except ValueError:
                console.print(f"[red]could not read '{updated}' as a date — use ISO or 'now'[/]")
                raise typer.Exit(1) from None

    with _session() as session:
        register_source(
            session,
            key,
            title=title,
            tier=tier,
            owner=owner,
            domain=domain,
            updated_at_source=updated_at,
            freshness_sla_hours=sla_hours,
        )
    colour = TIER_COLOUR.get(tier, "dim")
    console.print(f"[green]✓[/] [bold]{key}[/] → [{colour}]{tier}[/]")
    if sla_hours and updated_at is None:
        # A freshness SLA with no recorded update time is treated as a breach on
        # purpose — not knowing how old a source is, when policy says it must be
        # fresh, is not the same as it being fresh. Saying so here saves the operator
        # wondering why a source they just added reads as stale.
        console.print(
            f"  [yellow]![/] [dim]a {sla_hours}h SLA is set but no update time is "
            "recorded, so this reads as stale. Pass --updated when the source "
            "changes.[/]"
        )


def sources_import(
    file: Path = typer.Argument(..., help="JSON list of sources."),
) -> None:
    """Bulk-register from a JSON file.

    Tiering a corpus is inherently a bulk act. Nobody classifies four hundred sources
    one command at a time, and making them try is how the tiering never happens.
    """
    from ..provenance import TIERS, register_source

    try:
        payload = json.loads(file.read_text())
    except (OSError, ValueError) as exc:
        console.print(f"[red]could not read {file}: {exc}[/]")
        raise typer.Exit(1) from exc

    items = payload.get("sources", payload) if isinstance(payload, dict) else payload
    written = 0
    with _session() as session:
        for item in items:
            tier = item.get("tier", "unverified")
            if tier not in TIERS:
                console.print(f"[red]{item.get('key')}: unknown tier '{tier}'[/]")
                raise typer.Exit(1)
            register_source(
                session,
                item["key"],
                title=item.get("title", ""),
                tier=tier,
                owner=item.get("owner"),
                domain=item.get("domain"),
                freshness_sla_hours=item.get("freshness_sla_hours"),
                deprecated=item.get("deprecated", False),
            )
            written += 1
    console.print(f"[green]✓[/] registered {written} source(s) from {file.name}")


def sources_list(as_json: bool = typer.Option(False, "--json")) -> None:
    """Every registered source, worst tier first."""
    from sqlalchemy import select

    from ..models import SourceRecord
    from ..provenance import TIER_RANK, freshness_breach

    with _session() as session:
        rows = [
            {
                "key": r.key,
                "tier": r.tier,
                "owner": r.owner or "—",
                "domain": r.domain or "—",
                "deprecated": r.deprecated,
                "stale": bool(freshness_breach(r)),
                "unknown_age": bool(r.freshness_sla_hours and r.updated_at_source is None),
            }
            for r in session.scalars(select(SourceRecord))
        ]
    rows.sort(key=lambda r: (-TIER_RANK.get(r["tier"], 9), r["key"]))

    if as_json:
        console.print_json(json.dumps(rows))
        return
    if not rows:
        console.print("[dim]No sources registered.[/]")
        console.print(
            "[dim]Until sources are tiered, groundedness cannot tell an authoritative "
            "answer from a confident one. Add one with `agentfox sources add`.[/]"
        )
        return

    table = Table(box=None, padding=(0, 2), header_style="dim")
    for column in ("tier", "source", "owner", "domain", "state"):
        table.add_column(column)
    for row in rows:
        state = (
            "[red]deprecated[/]"
            if row["deprecated"]
            else "[yellow]age unknown[/]"
            if row["unknown_age"]
            else "[yellow]stale[/]"
            if row["stale"]
            else "[green]ok[/]"
        )
        table.add_row(
            f"[{TIER_COLOUR.get(row['tier'], 'dim')}]{row['tier']}[/]",
            row["key"][:52],
            row["owner"],
            row["domain"],
            state,
        )
    console.print(table)


# ---------------------------------------------------------------------------
# P11 — escalation
# ---------------------------------------------------------------------------


def escalation_set(
    agent: str | None = typer.Option(None, "--agent", help="Agent slug; omit for the default."),
    turn_depth: int | None = typer.Option(None, "--turn-depth"),
    repeated_failure: int | None = typer.Option(None, "--repeated-failure"),
    sla_minutes: int = typer.Option(60, "--sla-minutes"),
    owner_role: str = typer.Option("support", "--owner"),
    mode: str = typer.Option("observe", "--mode"),
) -> None:
    """Declare when this agent must hand off to a human (P11)."""
    from sqlalchemy import select

    from ..escalation import set_policy
    from ..models import Agent

    conditions: dict[str, Any] = {}
    if turn_depth is not None:
        conditions["turn_depth"] = turn_depth
    if repeated_failure is not None:
        conditions["repeated_failure"] = repeated_failure

    with _session() as session:
        agent_id = None
        if agent:
            record = session.scalar(select(Agent).where(Agent.slug == agent))
            if record is None:
                print_unknown_agent(console, session, agent)
                raise typer.Exit(1)
            agent_id = record.id
        policy = set_policy(
            session,
            agent_id=agent_id,
            conditions=conditions,
            owner_role=owner_role,
            sla_minutes=sla_minutes,
            mode=mode,
        )
        applied = dict(policy.conditions_json)

    console.print(f"[green]✓[/] escalation policy for [bold]{agent or 'all agents'}[/]")
    console.print(f"  owner {owner_role} · SLA {sla_minutes} min · {mode} mode")
    console.print(f"  [dim]conditions: {', '.join(sorted(applied))}[/]")


def escalation_scan(
    hours: int = typer.Option(24, "--hours"),
    apply: bool = typer.Option(False, "--apply", help="Raise findings and retroactive hand-offs."),
) -> None:
    """Which conversations qualified for a human and never got one.

    The largest single failure family at 31%, and invisible from inside the system: a
    conversation where the agent kept going instead of handing off looks entirely
    ordinary in the telemetry.
    """
    from ..escalation import detect_missed_escalation

    with _session() as session:
        result = detect_missed_escalation(session, since_hours=hours, raise_findings=apply)

    rate = result["missed_rate"]
    colour = "red" if rate > 0.05 else "green"
    console.print(
        f"[bold]{result['conversations']}[/] conversation(s) · "
        f"[bold]{result['qualified']}[/] qualified for escalation · "
        f"[{colour}]{len(result['missed'])} missed[/] ([{colour}]{rate:.1%}[/], target < 5%)"
    )
    for record in result["missed"][:10]:
        triggers = ", ".join(t["condition"] for t in record["triggers"][:3])
        console.print(
            f"  [dim]{record['session_id']}[/] {record['turns']} turns · "
            f"qualified at turn {record['first_qualifying_turn']} · {triggers}"
        )
    if result["missed"] and not apply:
        console.print(
            "\n  [dim]Read-only. Re-run with --apply to raise findings and retroactive "
            "hand-offs so the people still waiting are actually queued.[/]"
        )


# ---------------------------------------------------------------------------
# P10 — entitlement
# ---------------------------------------------------------------------------


def principal_set(
    subject: str = typer.Argument(..., help="IdP subject — an OIDC `sub` or employee id."),
    groups: str = typer.Option("", "--groups", "-g", help="Comma-separated groups."),
    clearances: str = typer.Option("", "--clearances", help="Restricted classes they may see."),
    residency: str | None = typer.Option(None, "--residency"),
    display: str = typer.Option("", "--display"),
) -> None:
    """Register the human an agent acts for (P10-1).

    Everything else in this pillar depends on this. The Copilot failure is its absence:
    the agent runs under its own identity, inherits everything that identity can reach,
    and every permission check passes.
    """
    from ..entitlement import upsert_principal

    with _session() as session:
        upsert_principal(
            session,
            subject,
            display=display,
            groups=[g.strip() for g in groups.split(",") if g.strip()],
            clearances=[c.strip() for c in clearances.split(",") if c.strip()],
            residency=residency,
        )
    console.print(f"[green]✓[/] principal [bold]{subject}[/]")
    if groups:
        console.print(f"  groups: {groups}")
    if clearances:
        console.print(f"  clearances: {clearances}")


def grant_add(
    resource: str = typer.Argument(..., help="Resource pattern, e.g. 'hr/*'."),
    principal: str = typer.Argument(..., help="Group or subject the grant is for."),
    kind: str = typer.Option("group", "--kind", help="group | subject"),
    classes: str = typer.Option("", "--classes", help="mnpi, legal_hold, pii_sensitive…"),
    purposes: str = typer.Option("", "--purposes", help="GDPR Art. 5(1)(b) purposes."),
) -> None:
    """Grant access to a resource pattern (P10-2)."""
    from ..entitlement import grant

    with _session() as session:
        grant(
            session,
            resource,
            principal=principal,
            principal_kind=kind,
            classes=[c.strip() for c in classes.split(",") if c.strip()],
            purposes=[p.strip() for p in purposes.split(",") if p.strip()],
        )
    console.print(f"[green]✓[/] [bold]{principal}[/] → {resource}")
    if classes:
        console.print(f"  [dim]carries {classes} — needs a matching clearance[/]")


def entitlement_report(days: int = typer.Option(7, "--days")) -> None:
    """How much more the agent can reach than its callers are entitled to (P10-4).

    Worth running before any entitlement model exists — a ratio of 1.0 with no grants
    configured is exactly the point.
    """
    from ..entitlement import over_permission_report

    with _session() as session:
        report = over_permission_report(session, days=days)

    if not report["requests"]:
        console.print(
            Panel(
                report["note"],
                title="[bold]No entitlement decisions[/]",
                title_align="left",
                border_style="yellow",
            )
        )
        console.print(
            "  [dim]Register a principal with `agentfox entitlement principal <subject>`, "
            "then filter retrieval through /api/entitlement/filter.[/]"
        )
        return

    ratio = report["over_permission"]
    colour = "red" if ratio > 0.2 else "yellow" if ratio else "green"
    console.print(
        f"[bold]{report['requests']}[/] request(s) · {report['principals']} principal(s) · "
        f"[{colour}]{ratio:.1%}[/] of retrieved content was withheld"
    )
    for reason, count in report["reasons"].items():
        console.print(f"  [dim]{reason:<22}{count}[/]")
    console.print(
        "\n  [dim]That share is what the agent could reach and the caller could "
        "not. It is the oversharing number, not an error rate.[/]"
    )


def register(app: typer.Typer) -> None:
    boundary_app = typer.Typer(
        help="Declare what an agent has no data for, so it says so instead of "
        "guessing (P7).",
        no_args_is_help=True,
    )
    boundary_app.command(name="set")(boundary_set)
    boundary_app.command(name="check")(boundary_check)
    app.add_typer(boundary_app, name="boundary")

    sources_app = typer.Typer(
        help="Say which sources are authoritative and how stale is too stale (P8).",
        no_args_is_help=True,
    )
    sources_app.command(name="add")(sources_add)
    sources_app.command(name="import")(sources_import)
    sources_app.command(name="list")(sources_list)
    app.add_typer(sources_app, name="sources")

    escalation_app = typer.Typer(
        help="Decide when an agent must hand a conversation to a person (P11).",
        no_args_is_help=True,
    )
    escalation_app.command(name="set")(escalation_set)
    escalation_app.command(name="scan")(escalation_scan)
    app.add_typer(escalation_app, name="escalation")

    entitlement_app = typer.Typer(
        help="Control what each end user is entitled to see (P10).",
        no_args_is_help=True,
    )
    entitlement_app.command(name="principal")(principal_set)
    entitlement_app.command(name="grant")(grant_add)
    entitlement_app.command(name="report")(entitlement_report)
    app.add_typer(entitlement_app, name="entitlement")
