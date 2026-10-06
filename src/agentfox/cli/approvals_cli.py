"""Approvals from the command line: what is waiting for a person, and deciding it.

A call held for a person (an ``escalate`` verdict) files an approval. Until this
module the queue was reachable only from the dashboard or by hand-written HTTP,
while the getting-started guide said it could be decided "from the dashboard or the
CLI" (#15). Lives under ``agentfox permit approvals``: deciding an approval is
granting one call.

Deciding writes to the audit chain exactly as the API route does, with the
deciding person named when ``--as`` is given.
"""

from __future__ import annotations

import json
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from agentfox.cli._style import match_id, short_id

console = Console()

approvals_app = typer.Typer(
    help="See the calls waiting for a person, and approve or deny them.",
    no_args_is_help=True,
)


def _session():
    from agentfox.core.db import init_db, session_scope

    init_db()
    return session_scope()


def _find(session, typed: str):
    """The approval the user named, by full id or by the short id `list` prints."""
    from sqlalchemy import select

    from agentfox.core.models import ApprovalRequest

    exact = session.get(ApprovalRequest, typed)
    if exact is not None:
        return exact
    matches = [a for a in session.scalars(select(ApprovalRequest)) if match_id(typed, a.id)]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        console.print(f"[red]unknown approval '{typed}'[/]")
        console.print("  List them with `agentfox permit approvals list --status all`.")
        raise typer.Exit(1)
    console.print(f"[red]'{typed}' matches {len(matches)} approvals.[/] Name one in full:")
    for match in matches:
        console.print(f"    {match.id}  [dim]{match.tool_key}[/]")
    raise typer.Exit(1)


def _row(approval, slugs: dict[str, str]) -> dict[str, Any]:
    from agentfox.core.models import as_aware

    def iso(value):
        value = as_aware(value)
        return value.isoformat() if value else None

    return {
        "id": approval.id,
        "agent": slugs.get(approval.agent_id or "", approval.agent_id),
        "tool": approval.tool_key,
        "arguments": approval.arguments_json or {},
        "reason": approval.reason,
        "status": approval.status,
        "requested_at": iso(approval.requested_at),
        "expires_at": iso(approval.expires_at),
        "trace_id": approval.trace_id,
        "decision_id": approval.decision_id,
        "rationale": approval.resolution_rationale,
        "resolver": approval.resolver_user_id,
    }


def _slugs(session) -> dict[str, str]:
    from sqlalchemy import select

    from agentfox.core.models import Agent

    return {a.id: a.slug for a in session.scalars(select(Agent))}


def _arguments(arguments: dict[str, Any]) -> str:
    text = json.dumps(arguments, default=str, ensure_ascii=False)
    return text if len(text) <= 80 else text[:79] + "…"


@approvals_app.command("list")
def approvals_list(
    status: str = typer.Option(
        "pending",
        "--status",
        help="pending (the default), approved, denied, expired, used, or all.",
    ),
    agent: str | None = typer.Option(None, "--agent", help="Only this agent's approvals."),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output for scripts."),
) -> None:
    """The calls held for a person. Unanswered ones expire, and expiry denies."""
    from sqlalchemy import select

    from agentfox.core.models import ApprovalRequest
    from agentfox.identity import APPROVAL_STATUSES, expire_stale_approvals

    if status != "all" and status not in APPROVAL_STATUSES:
        raise typer.BadParameter(
            f"choose one of {', '.join(APPROVAL_STATUSES)} or all", param_hint="--status"
        )
    with _session() as session:
        expire_stale_approvals(session)
        slugs = _slugs(session)
        query = select(ApprovalRequest).order_by(ApprovalRequest.requested_at.desc())
        if status != "all":
            query = query.where(ApprovalRequest.status == status)
        rows = [_row(a, slugs) for a in session.scalars(query)]
    if agent:
        rows = [r for r in rows if r["agent"] == agent]

    if as_json:
        console.print_json(json.dumps(rows, default=str))
        return
    if not rows:
        scope = f" for '{agent}'" if agent else ""
        console.print(f"[green]no {status if status != 'all' else ''} approvals{scope}[/]")
        return

    table = Table(box=None, padding=(0, 2), header_style="dim")
    table.add_column("id", no_wrap=True)
    table.add_column("status")
    table.add_column("agent", overflow="fold")
    table.add_column("call", overflow="fold", min_width=24)
    table.add_column("why", overflow="fold")
    for row in rows:
        table.add_row(
            f"[dim]{short_id(row['id'])}[/]",
            row["status"],
            row["agent"] or "—",
            f"{row['tool'] or '—'} {_arguments(row['arguments'])}",
            row["reason"] or "",
        )
    console.print(table)
    if status == "pending":
        console.print(
            "\n  [dim]Decide one with `agentfox permit approvals approve <id>` or `deny <id>`. "
            "An approved call runs once, when the agent retries it with the approval id.[/]"
        )


@approvals_app.command("show")
def approvals_show(
    approval_id: str = typer.Argument(..., help="Approval id, or the short id `list` prints."),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output for scripts."),
) -> None:
    """One approval in full: the call, its arguments, why it was held, and the decision."""
    from agentfox.identity import expire_stale_approvals

    with _session() as session:
        expire_stale_approvals(session)
        row = _row(_find(session, approval_id), _slugs(session))
    if as_json:
        console.print_json(json.dumps(row, default=str))
        return
    console.print(f"[bold]{row['id']}[/]  {row['status']}")
    console.print(f"  agent      {row['agent'] or '—'}")
    console.print(f"  call       {row['tool'] or '—'}")
    console.print(
        f"  arguments  {json.dumps(row['arguments'], default=str, ensure_ascii=False, indent=2)}"
    )
    console.print(f"  why        {row['reason']}")
    console.print(f"  requested  {row['requested_at']}")
    console.print(f"  expires    {row['expires_at']}")
    if row["trace_id"]:
        console.print(f"  trace      {row['trace_id']}")
    if row["rationale"] or row["resolver"]:
        console.print(f"  decided by {row['resolver'] or '—'}: {row['rationale'] or ''}")


def _decide(approval_id: str, approved: bool, rationale: str, actor: str | None) -> None:
    from agentfox.identity import resolve_approval
    from agentfox.prove.audit import chain

    who = actor or "cli"
    with _session() as session:
        approval = _find(session, approval_id)
        if approval.status != "pending":
            console.print(
                f"[yellow]{approval.id} is already {approval.status}[/]; nothing was changed."
            )
            raise typer.Exit(1)
        decided = resolve_approval(session, approval.id, approved, who[:40], rationale)
        chain.append(
            session,
            f"approval.{decided.status}",
            actor_type="user",
            actor_id=who,
            subject_type="approval",
            subject_id=decided.id,
            payload={"tool": decided.tool_key, "rationale": rationale, "reason": decided.reason},
        )
        status, resolved_id = decided.status, decided.id
        expires = decided.expires_at

    colour = {"approved": "green", "denied": "yellow"}.get(status, "red")
    console.print(f"[{colour}]{status}[/] {resolved_id}")
    if status == "approved":
        console.print(
            f"  The agent's retry with approval_id={resolved_id} runs once"
            + (f", until {expires:%Y-%m-%d %H:%M} UTC." if expires else ".")
        )
    elif status == "expired":
        console.print("  Nobody decided in time; an expired approval denies.")
        raise typer.Exit(1)


@approvals_app.command("approve")
def approvals_approve(
    approval_id: str = typer.Argument(..., help="Approval id, or the short id `list` prints."),
    rationale: str = typer.Option("", "--rationale", "-r", help="Why, for the audit record."),
    actor: str | None = typer.Option(
        None, "--as", help="Who is deciding (an email), for the audit record."
    ),
) -> None:
    """Let the held call run once: the same agent, tool and arguments, when retried."""
    _decide(approval_id, True, rationale, actor)


@approvals_app.command("deny")
def approvals_deny(
    approval_id: str = typer.Argument(..., help="Approval id, or the short id `list` prints."),
    rationale: str = typer.Option("", "--rationale", "-r", help="Why, for the audit record."),
    actor: str | None = typer.Option(
        None, "--as", help="Who is deciding (an email), for the audit record."
    ),
) -> None:
    """Refuse the held call. A retry presenting this approval escalates again."""
    _decide(approval_id, False, rationale, actor)


def register(app: typer.Typer) -> None:
    app.add_typer(approvals_app, name="approvals")
