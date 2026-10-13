"""Verify the recorded history (`agentfox report verify`)."""

from __future__ import annotations

import typer

from agentfox.apps.cli.commands._shared import _session, console

audit_app = typer.Typer(
    help="Check that the recorded history has not been altered.",
    no_args_is_help=True,
)


@audit_app.command("verify")
def audit_verify(start: int | None = None, end: int | None = None) -> None:
    """Verify the tamper-evident audit chain. Exits 1 if broken."""
    from agentfox.platform.ledger import chain

    with _session() as session:
        stats = chain.chain_stats(session)
        result = chain.verify_range(session, start, end)

    console.print(
        f"chain: [bold]{stats['entries']}[/] entries, head seq "
        f"{stats['head_seq']}, {stats['checkpoints']} checkpoints"
    )
    if result.valid:
        console.print(
            f"[bold green]CHAIN INTACT[/] — {result.entries_checked} entries "
            f"verified (seq {result.first_seq}..{result.last_seq})"
        )
        return
    console.print(f"[bold red]CHAIN TAMPERED[/] — {len(result.breaks)} break(s)")
    for issue in result.breaks[:10]:
        console.print(f"  [red]seq {issue.seq}[/] {issue.kind}: {issue.detail}")
    for failure in result.checkpoint_failures[:5]:
        console.print(f"  [red]checkpoint seq {failure['seq']}[/] {failure['reason']}")
    raise typer.Exit(1)


@audit_app.command("checkpoint")
def audit_checkpoint() -> None:
    """Write a signed checkpoint over the current chain head."""
    from agentfox.platform.ledger import chain

    with _session() as session:
        record = chain.checkpoint_now(session)
        if record is None:
            console.print("[yellow]chain is empty[/]")
            return
        console.print(f"[green]checkpoint[/] seq {record.seq} digest {record.digest[:16]}…")
