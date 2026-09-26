"""Capability grants from the command line.

A capability grant is what refuses an action after a detector has already been
fooled: the tool is not on the agent's list, or the amount is over its limit, or the
argument came from a document nobody trusts. Until this module existed the only way
to write one was ``POST /api/identities/{id}/capabilities``, which meant the half of
the product that survives a successful injection was reachable only by hand-written
HTTP. ``agentfox doctor`` graded a deployment on it and could not name a command.

Granting widens what an agent may do, so every command here writes what it did to
the audit chain, the same way ``agentfox policy enforce`` and ``agentfox agents
quarantine`` do.
"""

from __future__ import annotations

import datetime as dt
import json
from typing import Any

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ._style import match_id, print_unknown_agent, short_id

console = Console()

capability_app = typer.Typer(
    help="Grant, list and withdraw what an agent is allowed to do.",
    no_args_is_help=True,
)

#: Provenance levels, least to most dangerous. A grant's max-taint is the worst
#: provenance an argument may carry and still reach the tool without an approval.
TAINT_LEVELS = ("none", "user", "retrieved", "tool_result", "subagent", "memory")

_TAINT_MEANING = {
    "none": "no untrusted input at all",
    "user": "arguments the user typed, nothing retrieved",
    "retrieved": "arguments that may come from a retrieved document",
    "tool_result": "arguments that may come from another tool's output",
    "subagent": "arguments that may come from a sub-agent",
    "memory": "arguments that may come from the agent's own long-term memory",
}


def _session():
    from ..db import init_db, session_scope

    init_db()
    return session_scope()


def _parse_limit(raw: str) -> tuple[str, Any]:
    """Turn one ``--limit`` into an argument path and its constraint.

    ``amount:lt=1000``    the argument `amount` must be under 1000
    ``currency:in=USD,EUR`` the argument `currency` must be one of those
    ``region=eu``         the argument `region` must equal "eu"

    Values are read as JSON where that succeeds, so 1000 is a number and "1000" is a
    string. A comparison the engine does not implement is rejected here rather than
    stored and silently skipped at decision time.
    """
    from ..policy.model import COMPARATORS

    if "=" not in raw:
        raise typer.BadParameter(
            f"'{raw}' is not a limit. Write path=value, or path:op=value "
            f"(ops: {', '.join(sorted(COMPARATORS))}). Example: --limit amount:lt=1000"
        )
    left, _, value = raw.partition("=")
    path, _, op = left.partition(":")
    path = path.strip()
    op = op.strip()
    if not path:
        raise typer.BadParameter(f"'{raw}' has no argument path on the left of '='.")
    if op and op not in COMPARATORS:
        raise typer.BadParameter(
            f"unknown comparison '{op}' in '{raw}'. Use one of: {', '.join(sorted(COMPARATORS))}"
        )

    def _read(text: str) -> Any:
        try:
            return json.loads(text)
        except ValueError:
            return text

    if op in ("in", "not_in"):
        parsed: Any = [_read(part.strip()) for part in value.split(",") if part.strip()]
    else:
        parsed = _read(value.strip())
    return path, ({op: parsed} if op else parsed)


def _describe_constraints(constraints: dict[str, Any]) -> str:
    from ..identity.service import RESERVED_CONSTRAINTS

    bits = []
    for path, spec in (constraints or {}).items():
        if path in RESERVED_CONSTRAINTS:
            bits.append(f"{path}={spec}")
        elif isinstance(spec, dict):
            for op, value in spec.items():
                rendered = ", ".join(str(v) for v in value) if isinstance(value, list) else value
                bits.append(f"{path} {op} {rendered}")
        else:
            bits.append(f"{path} = {spec}")
    return "; ".join(bits) or "—"


def _resolve_identity(session, agent: str):
    """The identity for an agent slug, or the identity with that principal.

    Accepting both means `capability grant payments-ops payments.transfer` works
    without anyone having to learn that agents have identities.
    """
    from sqlalchemy import select

    from ..identity import ensure_identity
    from ..models import Agent, Identity

    record = session.scalar(select(Agent).where(Agent.slug == agent))
    if record is not None:
        return ensure_identity(session, record)
    identity = session.scalar(select(Identity).where(Identity.principal == agent))
    if identity is not None:
        return identity

    print_unknown_agent(console, session, agent)
    raise typer.Exit(1)


def _find_capability(session, typed: str):
    """The grant the user named, by full id or by the short id `capability list` prints.

    An abbreviation that matches two grants is refused rather than guessed, because
    the command on the other side of this lookup takes an agent's permission away.
    """
    from sqlalchemy import select

    from ..models import Capability

    exact = session.get(Capability, typed)
    if exact is not None:
        return exact
    matches = [c for c in session.scalars(select(Capability)) if match_id(typed, c.id)]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        console.print(f"[red]unknown capability '{typed}'[/]")
        console.print("  List the real ids with `agentfox capability list`.")
        raise typer.Exit(1)
    console.print(
        f"[red]'{typed}' matches {len(matches)} grants.[/] Name one of them in full:"
    )
    for match in matches:
        console.print(f"    {match.id}  [dim]{match.tool_key}[/]")
    raise typer.Exit(1)


def _audit(session, kind: str, capability, payload: dict[str, Any]) -> None:
    from ..audit import chain

    chain.append(
        session,
        kind,
        actor_type="user",
        actor_id="cli",
        subject_type="capability",
        subject_id=capability.id,
        payload=payload,
    )


@capability_app.command("grant")
def capability_grant(
    agent: str = typer.Argument(..., help="Agent slug, e.g. payments-ops."),
    tool: str = typer.Argument(
        ..., help="Tool key this grant covers. A glob is allowed: tickets.* or *."
    ),
    action: list[str] = typer.Option(
        [],
        "--action",
        "-a",
        help="Action on the tool this grant covers, repeatable. Default: every action.",
    ),
    limit: list[str] = typer.Option(
        [],
        "--limit",
        "-l",
        help="Argument limit, repeatable. path=value, or path:op=value — "
        "for example --limit amount:lt=1000 --limit currency:in=USD,EUR.",
    ),
    max_taint: str = typer.Option(
        "user",
        "--max-taint",
        help="Worst provenance an argument may carry and still go through without "
        f"an approval. One of: {', '.join(TAINT_LEVELS)}.",
    ),
    requires_approval: bool = typer.Option(
        False,
        "--requires-approval/--no-requires-approval",
        help="Send every matching call to a human before it runs.",
    ),
    expires_in_days: int | None = typer.Option(
        None,
        "--expires-in-days",
        help="Withdraw the grant automatically after this many days. Default: no expiry.",
    ),
    granted_by: str = typer.Option(
        "cli", "--granted-by", help="Who is accountable for this grant. Recorded in the audit."
    ),
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Skip the confirmation prompt (for scripts and CI)."
    ),
) -> None:
    """Allow an agent to call a tool, and say under what limits.

    Least privilege is default deny: an agent with no grant for a tool cannot call
    it, whether or not a detector fires. This command is the only thing that widens
    that, so it asks before it writes and records the result in the audit chain.
    """
    from ..models import utcnow

    if max_taint not in TAINT_LEVELS:
        console.print(
            f"[red]unknown provenance level '{max_taint}'[/]. "
            f"Use one of: {', '.join(TAINT_LEVELS)}"
        )
        raise typer.Exit(2)

    constraints: dict[str, Any] = {}
    for raw in limit:
        path, spec = _parse_limit(raw)
        constraints[path] = spec
    actions = list(action) or ["*"]
    expires_at = (
        utcnow() + dt.timedelta(days=expires_in_days) if expires_in_days is not None else None
    )

    # Resolve the agent before describing the grant: telling someone what is about to
    # happen and then failing on the name they typed wastes the confirmation.
    with _session() as session:
        principal = _resolve_identity(session, agent).principal

    console.print(f"[bold]Grant[/] {tool} to [bold]{agent}[/]  [dim]{principal}[/]")
    console.print(f"  actions        {', '.join(actions)}")
    console.print(f"  argument limits {_describe_constraints(constraints)}")
    console.print(
        f"  max provenance {max_taint}  [dim]{_TAINT_MEANING.get(max_taint, '')}[/]"
    )
    console.print(
        f"  human approval {'required for every call' if requires_approval else 'not required'}"
    )
    console.print(
        f"  expires        {expires_at.isoformat(timespec='seconds') if expires_at else 'never'}"
    )
    if not yes and not typer.confirm(
        "\nThis widens what the agent may do. Grant it?", default=False
    ):
        console.print("[yellow]nothing granted[/]")
        raise typer.Exit(1)

    from ..identity import grant_capability

    with _session() as session:
        identity = _resolve_identity(session, agent)
        capability = grant_capability(
            session,
            identity,
            tool,
            actions=actions,
            constraints=constraints,
            requires_approval=requires_approval,
            max_taint=max_taint,
            granted_by=granted_by,
            expires_at=expires_at,
        )
        capability_id = capability.id
        _audit(
            session,
            "capability.granted",
            capability,
            {
                "principal": principal,
                "tool_key": tool,
                "actions": actions,
                "constraints": constraints,
                "requires_approval": requires_approval,
                "max_taint": max_taint,
                "expires_at": expires_at.isoformat() if expires_at else None,
                "granted_by": granted_by,
            },
        )

    console.print(f"\n[green]granted[/] [bold]{capability_id}[/]  [dim]{principal}[/]")
    _next_steps(
        [
            (
                f"agentfox capability list {agent}",
                "see everything this agent may now do",
            ),
            (
                f"agentfox capability revoke {capability_id}",
                "withdraw this grant again",
            ),
            ("agentfox doctor", "re-grade least privilege for this deployment"),
        ]
    )


@capability_app.command("list")
def capability_list(
    agent: str | None = typer.Argument(
        None, help="Agent slug. Omit to list every agent's grants."
    ),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output for scripts."),
) -> None:
    """What each agent is allowed to do. Anything not listed here is refused."""
    from sqlalchemy import select

    from ..models import Agent, Capability, Identity, as_aware, utcnow

    with _session() as session:
        identities = {i.id: i for i in session.scalars(select(Identity))}
        slugs = {a.id: a.slug for a in session.scalars(select(Agent))}
        now = utcnow()
        rows = []
        for capability in session.scalars(select(Capability).order_by(Capability.tool_key)):
            identity = identities.get(capability.identity_id)
            slug = slugs.get(identity.agent_id) if identity else None
            name = slug or (identity.principal if identity else "?")
            if agent and agent not in (slug, identity.principal if identity else None):
                continue
            expires_at = as_aware(capability.expires_at)
            rows.append(
                {
                    "id": capability.id,
                    "agent": name,
                    "tool_key": capability.tool_key,
                    "actions": list(capability.actions or ["*"]),
                    "constraints": dict(capability.constraints_json or {}),
                    "max_taint": capability.max_taint,
                    "requires_approval": capability.requires_approval,
                    "granted_by": capability.granted_by,
                    "expires_at": expires_at.isoformat() if expires_at else None,
                    "expired": bool(expires_at and expires_at <= now),
                }
            )

    if as_json:
        console.print_json(json.dumps(rows, default=str))
        return

    if not rows:
        scope = f" for '{agent}'" if agent else ""
        console.print(f"[yellow]no capability grants{scope}[/]")
        console.print(
            "  Every tool call is refused by default. Grant one with "
            "`agentfox capability grant <agent> <tool>`."
        )
        return

    # Columns that say the same thing on every row carry no information and cost the
    # width that the argument limits need in order to stay readable.
    show_agent = agent is None

    table = Table(box=None, padding=(0, 2), header_style="dim")
    table.add_column("id", no_wrap=True)
    if show_agent:
        table.add_column("agent", overflow="fold")
    table.add_column("may call", overflow="fold", min_width=22)
    table.add_column("as long as", overflow="fold")
    for row in rows:
        conditions = [_describe_constraints(row["constraints"])] if row["constraints"] else []
        conditions.append(f"provenance up to {row['max_taint']}")
        if row["requires_approval"]:
            conditions.append("a human approves")
        if row["expired"]:
            conditions.append("[red]expired, no longer matched[/]")
        elif row["expires_at"]:
            conditions.append(f"before {row['expires_at'][:10]}")
        actions = ", ".join(row["actions"])
        tool = row["tool_key"] if actions == "*" else f"{row['tool_key']} [{actions}]"
        cells = [f"[dim]{short_id(row['id'])}[/]"]
        if show_agent:
            cells.append(row["agent"])
        cells.extend([tool, "; ".join(conditions)])
        table.add_row(*cells, style="dim" if row["expired"] else None)
    console.print(table)

    expired = [r for r in rows if r["expired"]]
    console.print(
        f"\n  [dim]{len(rows)} grant(s)"
        + (f", {len(expired)} past their expiry and no longer matched" if expired else "")
        + ". Anything not listed is refused by default.[/]"
    )
    console.print(
        "  [dim]provenance is where an argument came from: 'user' means typed by a "
        "person, 'tool_result' means it may have come out of another tool.[/]"
    )


@capability_app.command("revoke")
def capability_revoke(
    capability_id: str = typer.Argument(
        ..., help="Grant id from `agentfox capability list`, e.g. cap_01h...."
    ),
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Skip the confirmation prompt (for scripts and CI)."
    ),
) -> None:
    """Withdraw a grant. The agent's calls to that tool are refused from now on."""
    from sqlalchemy import select

    from ..identity import revoke_capability
    from ..models import Agent, Identity

    with _session() as session:
        capability = _find_capability(session, capability_id)
        identity = session.get(Identity, capability.identity_id)
        slug = None
        if identity is not None and identity.agent_id:
            agent = session.scalar(select(Agent).where(Agent.id == identity.agent_id))
            slug = agent.slug if agent else None
        name = slug or (identity.principal if identity else "?")
        shape = {
            "principal": identity.principal if identity else None,
            "tool_key": capability.tool_key,
            "actions": list(capability.actions or ["*"]),
            "constraints": dict(capability.constraints_json or {}),
            "requires_approval": capability.requires_approval,
            "max_taint": capability.max_taint,
        }
        tool_key = capability.tool_key
        resolved_id = capability.id

        console.print(
            f"[bold]Revoke[/] {tool_key} from [bold]{name}[/]  [dim]{resolved_id}[/]"
        )
        console.print(f"  argument limits {_describe_constraints(shape['constraints'])}")
        if not yes and not typer.confirm(
            "\nCalls to this tool will be refused. Revoke it?", default=False
        ):
            console.print("[yellow]nothing revoked[/]")
            raise typer.Exit(1)

        revoked = revoke_capability(session, resolved_id)
        if revoked is not None:
            _audit(session, "capability.revoked", revoked, shape)

    console.print(f"\n[green]revoked[/] {tool_key} from [bold]{name}[/]")
    console.print(
        "  [dim]The grant is gone from the live set; the audit chain keeps what it was.[/]"
    )


def _next_steps(steps: list[tuple[str, str]]) -> None:
    table = Table(show_header=False, box=None, padding=(0, 2))
    for command, why in steps:
        table.add_row(f"[bold cyan]{command}[/]", f"[dim]{why}[/]")
    console.print()
    console.print(Panel(table, title="[bold]Next[/]", title_align="left", border_style="dim"))


def register(app: typer.Typer) -> None:
    app.add_typer(capability_app, name="capability")
