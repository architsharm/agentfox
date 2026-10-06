"""`agentfox policy proposals` — the governed improvement loop's inbox: review, decide,
apply, undo.
"""

from __future__ import annotations

import json

import typer
from rich.panel import Panel
from rich.table import Table

from agentfox.apps.cli.commands._shared import _emit, _session, console

proposals_app = typer.Typer(
    help="Proposed changes to governance configuration: review, decide, apply, undo.",
    no_args_is_help=True,
)


def _load_proposal(session, proposal_id: str):
    from agentfox.capabilities.improvement.proposals import get_proposal

    proposal = get_proposal(session, proposal_id)
    if proposal is None:
        console.print(f"[red]unknown proposal '{proposal_id}'[/]")
        raise typer.Exit(1)
    return proposal


def _proposal_step(proposal_id: str, step) -> None:
    """Run one lifecycle step; a refused step exits non-zero and changes nothing."""
    from agentfox.capabilities.improvement.proposals import proposal_json

    with _session() as session:
        proposal = _load_proposal(session, proposal_id)
        try:
            step(session, proposal)
        except ValueError as exc:
            console.print(f"[red]refused:[/] {exc}")
            raise typer.Exit(1) from exc
        body = proposal_json(proposal)
    note = " (awaiting a second approver)" if body["awaiting_second_approver"] else ""
    console.print(f"[bold]{body['id']}[/] → [bold]{body['status']}[/]{note}")


@proposals_app.command("list")
def proposals_list(
    status: str | None = typer.Option(None, help="Filter by lifecycle status"),
    kind: str | None = typer.Option(None, help="Filter by change kind"),
    scope_level: str | None = typer.Option(None, "--scope", help="org | team | agent | user"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """List proposals, newest first."""
    from agentfox.capabilities.improvement.proposals import list_proposals, proposal_json

    with _session() as session:
        rows = [
            proposal_json(p)
            for p in list_proposals(session, status=status, kind=kind, scope_level=scope_level)
        ]
    if as_json:
        _emit({"proposals": rows}, True)
        return
    if not rows:
        # The only list command in the CLI that printed a bare header row and
        # stopped. Every other one says what is missing and how to get some.
        filtered = any((status, kind, scope_level))
        console.print(
            "[dim]no proposals match that filter[/]"
            if filtered
            else "[dim]no proposals — `agentfox policy proposals from-traffic` files grants and "
            "tool declarations from the calls your agents have made; `agentfox policy "
            "proposals from-labels` files rule cut-offs from false positives you have labelled.[/]"
        )
        return
    table = Table(box=None, pad_edge=False)
    for column in ("id", "status", "kind", "direction", "autonomy", "scope", "title"):
        table.add_column(column, style="bold" if column == "id" else None)
    for row in rows:
        colour = "red" if row["direction"] == "loosens" else "green"
        table.add_row(
            row["id"],
            row["status"],
            row["kind"],
            f"[{colour}]{row['direction']}[/]",
            row["autonomy_level"],
            f"{row['scope_level']}:{row['scope_id']}",
            row["title"][:60],
        )
    console.print(table)


@proposals_app.command("show")
def proposals_show(proposal_id: str, as_json: bool = typer.Option(False, "--json")) -> None:
    """Show one proposal: its diff, evidence, proof and decisions."""
    from agentfox.capabilities.improvement.proposals import proposal_json

    with _session() as session:
        body = proposal_json(_load_proposal(session, proposal_id))
    if as_json:
        _emit(body, True)
        return
    console.print(
        Panel.fit(
            f"[bold]{body['title']}[/]\n"
            f"status     {body['status']}\n"
            f"kind       {body['kind']} ({body['direction']}, {body['autonomy_level']})\n"
            f"scope      {body['scope_level']}:{body['scope_id']}\n"
            f"target     {body['target_type']}:{body['target_ref']}\n"
            f"proposed   {body['proposed_by']}\n"
            f"decided    {body['decided_by'] or '-'}"
            f"{' + ' + body['second_approver'] if body['second_approver'] else ''}\n"
            f"rationale  {body['rationale']}",
            border_style="cyan",
        )
    )
    console.print_json(json.dumps({"diff": body["diff"], "proof": body["proof"]}, default=str))


@proposals_app.command("approve")
def proposals_approve(
    proposal_id: str,
    actor: str = typer.Option(..., "--actor", help="Your name or email — decisions are named"),
    note: str = typer.Option(..., "--note", help="Why"),
) -> None:
    """Approve a proven proposal. An org-level loosening needs two different people."""
    from agentfox.capabilities.improvement.proposals import decide

    _proposal_step(proposal_id, lambda s, p: decide(s, p, approve=True, actor=actor, note=note))


@proposals_app.command("reject")
def proposals_reject(
    proposal_id: str,
    actor: str = typer.Option(..., "--actor", help="Your name or email — decisions are named"),
    note: str = typer.Option(..., "--note", help="Why"),
) -> None:
    """Reject a proposal."""
    from agentfox.capabilities.improvement.proposals import decide

    _proposal_step(proposal_id, lambda s, p: decide(s, p, approve=False, actor=actor, note=note))


@proposals_app.command("apply")
def proposals_apply(
    proposal_id: str,
    actor: str | None = typer.Option(None, "--actor", help="Your name or email"),
    automated: bool = typer.Option(
        False,
        "--automated",
        help="Apply as the improvement loop, subject to autonomy, freeze and daily cap",
    ),
) -> None:
    """Apply an approved proposal (or settle one whose canary has finished)."""
    from agentfox.capabilities.improvement.proposals import apply_proposal

    if not automated and not actor:
        console.print("[red]--actor is required unless --automated[/]")
        raise typer.Exit(1)
    _proposal_step(
        proposal_id,
        lambda s, p: apply_proposal(s, p, actor=actor, automated=automated),
    )


@proposals_app.command("rollback")
def proposals_rollback(
    proposal_id: str,
    actor: str = typer.Option(..., "--actor", help="Your name or email"),
    reason: str = typer.Option(..., "--reason", help="Why it is being undone"),
) -> None:
    """Undo an applied or canaried proposal."""
    from agentfox.capabilities.improvement.proposals import rollback_proposal

    _proposal_step(
        proposal_id,
        lambda s, p: rollback_proposal(s, p, reason=reason, actor=actor),
    )


@proposals_app.command("verify")
def proposals_verify(
    proposal_id: str,
    actor: str = typer.Option(..., "--actor", help="Your name or email"),
    note: str = typer.Option(..., "--note", help="What the evidence showed"),
    failed: bool = typer.Option(
        False, "--failed", help="The change did not do what it promised: record it and roll back."
    ),
) -> None:
    """Close the loop on an applied change: did it do what it promised?

    `--failed` rolls the change back. If undoing it would loosen a control, it stays
    applied with the failure recorded, because that rollback is a person's decision.
    """
    from agentfox.capabilities.improvement.proposals import verify_proposal

    _proposal_step(
        proposal_id,
        lambda s, p: verify_proposal(s, p, verified=not failed, note=note, actor=actor),
    )


@proposals_app.command("from-labels")
def proposals_from_labels(
    days: int = typer.Option(30, help="Label window in days"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """File rule cut-off proposals from labelled false positives. Nothing is applied."""
    from agentfox.capabilities.improvement.loops import propose_threshold_changes

    with _session() as session:
        report = propose_threshold_changes(session, days=days).to_json()
    if as_json:
        _emit(report, True)
        return
    console.print(
        f"filed {len(report['filed'])}, refreshed {len(report['refreshed'])}, "
        f"superseded {len(report['superseded'])}"
    )
    for skip in report["skipped"]:
        where = "/".join(str(skip[k]) for k in ("detector_key", "policy", "rule_id") if k in skip)
        console.print(f"  [dim]skipped {where}: {skip['reason']}[/]")


@proposals_app.command("from-traffic")
def proposals_from_traffic(
    agent: str | None = typer.Option(None, "--agent", help="Only this agent's calls (slug)."),
    since: str | None = typer.Option(
        None, "--since", help="Window: 7d, 24h, 30m or an ISO date. Default: the last 30 days."
    ),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Propose tool declarations and grants from what your agents have called.

    Learned permissions: observe, propose, approve. Reads every recorded tool call —
    refused ones included — and files a `tool.declare` for each undeclared tool and a
    `capability.grant` per agent and tool, with argument limits read off the calls and
    a provenance ceiling from benign calls only. A call a detector matched, or that was
    stopped for where its arguments came from and nobody approved, is never learned
    from. Nothing is applied: approve and apply each proposal.
    """
    from agentfox.capabilities.improvement.proposals import get_proposal
    from agentfox.capabilities.improvement.traffic import parse_since, propose_from_traffic

    try:
        window = parse_since(since)
    except ValueError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(2) from exc
    with _session() as session:
        report = propose_from_traffic(session, agent=agent, since=window)
        body = report.to_json()
        titles = {}
        for pid in body["filed"] + body["refreshed"]:
            proposal = get_proposal(session, pid)
            if proposal is not None:
                titles[pid] = (proposal.kind, proposal.status, proposal.title)
    if as_json:
        _emit(body, True)
        return

    calls = body["calls"]
    console.print(
        f"read {sum(calls.values())} tool call(s): {calls.get('benign', 0)} benign, "
        f"{calls.get('held', 0)} held for provenance, {calls.get('flagged', 0)} flagged"
    )
    console.print(
        f"filed {len(body['filed'])}, refreshed {len(body['refreshed'])}, "
        f"superseded {len(body['superseded'])}, verified {len(body['verified'])}"
    )
    for pid in body["filed"] + body["refreshed"]:
        kind, status, title = titles[pid]
        console.print(f"  [bold]{pid}[/]  [dim]{kind} · {status}[/]\n      {title}")
    for skip in body["skipped"]:
        where = "/".join(str(skip[k]) for k in ("agent", "tool_key") if k in skip)
        console.print(f"  [dim]skipped {where}: {skip['reason']}[/]")
    if body["filed"] or body["refreshed"]:
        console.print(
            "\n  [dim]Next: `agentfox policy proposals show <id>`, then "
            "`agentfox policy proposals approve <id> --actor you@example.com --note why` and "
            "`agentfox policy proposals apply <id> "
            "--actor you@example.com`. Tool declarations are org-wide loosenings and need "
            "two different approvers.[/]"
        )
