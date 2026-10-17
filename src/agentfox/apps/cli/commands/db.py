"""`agentfox admin db` — apply, roll back and inspect the database schema."""

from __future__ import annotations

import typer

from agentfox.apps.cli.commands._shared import console

db_app = typer.Typer(help="Apply, roll back and inspect the database schema.", no_args_is_help=True)


@db_app.command("upgrade")
def db_upgrade(revision: str = "head") -> None:
    """Apply migrations. This is how a deployed instance is upgraded."""
    from agentfox.core.db import current_revision, upgrade_db

    before = current_revision()
    upgrade_db(revision)
    after = current_revision()
    console.print(f"[green]migrated[/] {before or 'empty'} → [bold]{after}[/]")


@db_app.command("downgrade")
def db_downgrade(revision: str = typer.Argument(..., help="Target revision, or 'base'.")) -> None:
    """Roll back migrations. Every migration ships with a tested downgrade."""
    from agentfox.core.db import current_revision, downgrade_db

    before = current_revision()
    downgrade_db(revision)
    console.print(f"[yellow]rolled back[/] {before} → [bold]{current_revision() or 'base'}[/]")


@db_app.command("current")
def db_current() -> None:
    """Show the applied schema revision."""
    from agentfox.core.db import current_revision

    revision = current_revision()
    console.print(
        f"schema revision: [bold]{revision or 'none — run `agentfox admin db upgrade`'}[/]"
    )
