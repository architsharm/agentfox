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
    from agentfox.apps.cli import account as _account
    from agentfox.platform.ledger import chain

    remote = _account.use(console)
    if remote is not None:
        # The account's chain, verified where it is kept (`POST /api/audit/verify`).
        try:
            result = remote.request(
                "POST",
                "/api/audit/verify",
                params={k: v for k, v in (("start_seq", start), ("end_seq", end)) if v is not None},
            )
        except _account.AccountError as exc:
            _account.fail(console, exc)
        stats = result.get("stats") or {}
    else:
        with _session() as session:
            stats = chain.chain_stats(session)
            result = chain.verify_range(session, start, end).to_json()

    console.print(
        f"chain: [bold]{stats.get('entries')}[/] entries, head seq "
        f"{stats.get('head_seq')}, {stats.get('checkpoints')} checkpoints"
    )
    if result.get("valid"):
        console.print(
            f"[bold green]CHAIN INTACT[/] — {result.get('entries_checked')} entries "
            f"verified (seq {result.get('first_seq')}..{result.get('last_seq')})"
        )
        return
    breaks = result.get("breaks") or []
    console.print(f"[bold red]CHAIN TAMPERED[/] — {len(breaks)} break(s)")
    for issue in breaks[:10]:
        console.print(
            f"  [red]seq {issue.get('seq')}[/] {issue.get('kind')}: {issue.get('detail')}"
        )
    for failure in (result.get("checkpoint_failures") or [])[:5]:
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
