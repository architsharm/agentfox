"""Operator token management.

Tokens are the only way into a production control plane, so minting one has to be a
single obvious command. If it is not, the pressure to leave the development header
enabled becomes the path of least resistance — and that is how the finding this closes
came to exist in the first place.
"""

from __future__ import annotations

from typing import Any

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()


def _session():
    """A session on an initialised database. `init_db` is idempotent, and without it
    a command run before `agentfox init` dies on "no such table"."""
    from agentfox.core.db import init_db, session_scope

    init_db()
    return session_scope()


def issue(
    email: str = typer.Argument(..., help="Operator the token acts as."),
    name: str = typer.Option("", "--name", "-n", help="What this token is for."),
    days: int = typer.Option(365, "--days", help="Lifetime; 0 for no expiry."),
) -> None:
    """Mint an API token. The value is shown once and cannot be retrieved again."""
    from sqlalchemy import select

    from agentfox.core.models import User
    from agentfox.core.tenancy import bind_session, system_scope
    from agentfox.gateway.auth import issue_token

    with system_scope("issuing an operator token"), _session() as session:
        user = session.scalar(select(User).where(User.email == email))
        if user is None:
            console.print(
                f"[red]unknown user '{email}'[/]\n"
                f"  [dim]Create the operator first (no demo data is loaded):[/]\n"
                f"    agentfox admin users create {email} --role owner"
            )
            raise typer.Exit(1)
        # The lookup above has to run unfiltered (that's what system_scope is for —
        # the recipient's org isn't known yet). Once it is, bind the session to it so
        # the audit entry `issue_token` records lands in the recipient's own chain
        # rather than whichever tenant the session happened to default to.
        bind_session(session, user.org_id)
        token, raw = issue_token(session, user, name=name, ttl_days=days or None)
        summary = {
            "id": token.id,
            "name": token.name,
            "org": user.org_id,
            "role": user.role,
            "expires": token.expires_at.isoformat() if token.expires_at else "never",
        }

    console.print(
        Panel(
            f"[bold]{raw}[/]\n\n"
            f"[dim]{summary['name']} · {email} · {summary['role']} · org {summary['org']}\n"
            f"expires {summary['expires']}[/]",
            title="[bold]Token issued — copy it now[/]",
            title_align="left",
            border_style="yellow",
        )
    )
    # Only the argon2 hash is stored, so this really is the only time it exists in a
    # readable form. Saying so plainly is cheaper than a support conversation later.
    console.print(
        "  [dim]Only a hash is stored. There is no way to show this value again — "
        "issue a new token if it is lost.[/]"
    )
    console.print(f'  [dim]Use: curl -H "Authorization: Bearer {raw[:16]}…"[/]')


def tokens(as_json: bool = typer.Option(False, "--json")) -> None:
    """List tokens. Never shows a secret — there is nothing stored that could."""
    import json

    from sqlalchemy import select

    from agentfox.core.models import ApiToken, User, utcnow
    from agentfox.core.tenancy import system_scope
    from agentfox.prove.audit import system_log

    now = utcnow()
    rows: list[dict[str, Any]] = []
    with system_scope("listing operator tokens"), _session() as session:
        users = {u.id: u for u in session.scalars(select(User))}
        tokens_seen = list(session.scalars(select(ApiToken).order_by(ApiToken.created_at.desc())))
        for token in tokens_seen:
            expires = token.expires_at
            if expires is not None and expires.tzinfo is None:
                import datetime as dt

                expires = expires.replace(tzinfo=dt.UTC)
            state = (
                "revoked"
                if token.revoked_at
                else "expired"
                if expires is not None and expires <= now
                else "active"
            )
            user = users.get(token.user_id)
            rows.append(
                {
                    "id": token.id,
                    "name": token.name,
                    "prefix": token.key_prefix,
                    "user": user.email if user else token.user_id,
                    "role": user.role if user else "?",
                    "org": token.org_id,
                    "state": state,
                    "expires": expires.isoformat() if expires else "never",
                }
            )
        # This read has no single tenant to attribute to — it is, by definition, a
        # view across every one of them — so it goes to the system chain rather than
        # being silently dropped into whichever tenant the session defaults to (the
        # thing `operator_log.py` and `system_log.py` both warn against faking).
        system_log.record(
            session,
            "system.tokens.listed",
            actor="cli",
            reason="listing operator tokens",
            subject_type="api_token",
            extra={"count": len(tokens_seen), "orgs": len({t.org_id for t in tokens_seen})},
        )

    if as_json:
        console.print_json(json.dumps(rows, default=str))
        return
    if not rows:
        console.print(
            "[dim]No tokens issued. Create one with `agentfox admin auth issue <email>`.[/]"
        )
        return

    table = Table(box=None, padding=(0, 2), header_style="dim")
    for column in ("state", "name", "user", "role", "prefix", "expires"):
        table.add_column(column)
    for row in rows:
        colour = {"active": "green", "revoked": "dim", "expired": "yellow"}[row["state"]]
        table.add_row(
            f"[{colour}]{row['state']}[/]",
            row["name"],
            row["user"],
            row["role"],
            f"[dim]{row['prefix']}…[/]",
            f"[dim]{row['expires'][:10]}[/]",
        )
    console.print(table)


def revoke(
    token_id: str = typer.Argument(..., help="Token id from `agentfox admin auth tokens`."),
) -> None:
    """Revoke a token immediately."""
    from agentfox.core.models import ApiToken
    from agentfox.core.tenancy import bind_session, system_scope
    from agentfox.gateway.auth import revoke_token

    with system_scope("revoking an operator token"), _session() as session:
        token = session.get(ApiToken, token_id)
        if token is None:
            console.print(f"[yellow]{token_id} is unknown or already revoked[/]")
            raise typer.Exit(1)
        # Same reasoning as `issue`: the token's own org is known as soon as it is
        # looked up, so bind to it before recording the revocation, rather than
        # letting the entry fall back to whichever tenant the session defaults to.
        bind_session(session, token.org_id)
        if not revoke_token(session, token_id):
            console.print(f"[yellow]{token_id} is unknown or already revoked[/]")
            raise typer.Exit(1)
    console.print(f"[green]revoked[/] {token_id}")


def status() -> None:
    """How this deployment authenticates, and whether that is what you intended."""
    from agentfox.core.config import get_settings
    from agentfox.gateway.auth import header_identity_allowed

    settings = get_settings()
    allowed = header_identity_allowed()
    if allowed:
        console.print(
            Panel(
                f"[yellow]The X-Nometria-User header is accepted.[/]\n\n"
                f"[dim]environment = {settings.environment} · auth_mode = "
                f"{settings.auth_mode}\n"
                "Anyone who can reach this port is any user they name. That is fine for "
                "local work and unacceptable anywhere else.\n\n"
                "Set AGENTFOX_ENVIRONMENT=production, or AGENTFOX_AUTH_MODE=token, to "
                "require API tokens.[/]",
                title="[bold]Authentication: development mode[/]",
                title_align="left",
                border_style="yellow",
            )
        )
    else:
        console.print(
            Panel(
                "[green]API tokens required.[/]\n\n"
                f"[dim]environment = {settings.environment} · auth_mode = "
                f"{settings.auth_mode}\n"
                "The development identity header is refused.[/]",
                title="[bold]Authentication: enforced[/]",
                title_align="left",
                border_style="green",
            )
        )


def create_user(
    email: str = typer.Argument(..., help="The operator's email; what `auth issue` takes."),
    role: str = typer.Option(
        "owner",
        "--role",
        "-r",
        help="owner | admin | security | compliance | developer | auditor.",
    ),
    name: str = typer.Option("", "--name", "-n", help="Display name."),
    org: str = typer.Option(
        "", "--org", help="Tenant to create them in. Default: this deployment's AGENTFOX_ORG_ID."
    ),
    token: bool = typer.Option(
        False, "--token", help="Also issue an API token for them now, shown once."
    ),
) -> None:
    """Create an operator — the first one on a fresh self-hosted install, with no demo data.

    Then `agentfox admin auth issue EMAIL` mints their API token (or pass --token).
    """
    from agentfox.gateway.auth import OperatorExists, create_operator, issue_token

    with _session() as session:
        try:
            user = create_operator(session, email, role=role, name=name, org_id=org or None)
        except OperatorExists as exc:
            console.print(f"[yellow]{exc}[/]")
            raise typer.Exit(1) from exc
        except ValueError as exc:
            console.print(f"[red]{exc}[/]")
            raise typer.Exit(2) from exc
        raw = None
        if token:
            _rec, raw = issue_token(session, user, name="first-operator")
        org_id, user_role = user.org_id, user.role
    console.print(f"[green]created[/] {email} · {user_role} · org {org_id}")
    if raw:
        console.print(
            Panel(
                f"[bold]{raw}[/]",
                title="[bold]Token issued — copy it now[/]",
                title_align="left",
                border_style="yellow",
            )
        )
        console.print("  [dim]Only a hash is stored; this value cannot be shown again.[/]")
    else:
        console.print(f"  [dim]Next: agentfox admin auth issue {email}[/]")


def list_users(as_json: bool = typer.Option(False, "--json")) -> None:
    """List operators in every tenant on this database."""
    import json

    from sqlalchemy import select

    from agentfox.core.models import User
    from agentfox.core.tenancy import system_scope

    with system_scope("listing operators"), _session() as session:
        rows = [
            {"email": u.email, "role": u.role, "org": u.org_id, "active": u.active}
            for u in session.scalars(select(User).order_by(User.org_id, User.email))
        ]
    if as_json:
        console.print_json(json.dumps(rows))
        return
    if not rows:
        console.print(
            "[dim]No operators. Create one with "
            "`agentfox admin users create EMAIL --role owner`.[/]"
        )
        return
    table = Table(box=None, padding=(0, 2), header_style="dim")
    for column in ("email", "role", "org", "active"):
        table.add_column(column)
    for row in rows:
        table.add_row(row["email"], row["role"], row["org"], "yes" if row["active"] else "no")
    console.print(table)


def register(app: typer.Typer) -> None:
    auth_app = typer.Typer(help="Operator tokens and authentication mode.", no_args_is_help=True)
    auth_app.command(name="issue")(issue)
    auth_app.command(name="tokens")(tokens)
    auth_app.command(name="revoke")(revoke)
    auth_app.command(name="status")(status)
    app.add_typer(auth_app, name="auth")
    users_app = typer.Typer(
        help="Operators: create the first one on a fresh install, list them.",
        no_args_is_help=True,
    )
    users_app.command(name="create")(create_user)
    users_app.command(name="list")(list_users)
    app.add_typer(users_app, name="users")
