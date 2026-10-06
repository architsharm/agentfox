"""Verify the recorded history and export it (`agentfox report verify`, `report evidence`)."""

from __future__ import annotations

import datetime as dt

import typer

from agentfox.cli.commands._shared import _session, console

audit_app = typer.Typer(
    help="Check that the recorded history has not been altered.",
    no_args_is_help=True,
)


evidence_app = typer.Typer(
    help="Export a package an auditor can verify without us.",
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


def _evidence_period(
    from_: str | None, to: str | None, since_days: int
) -> tuple[dt.datetime, dt.datetime | None]:
    """Resolve the package's period from either an explicit range or a lookback.

    An auditor asks for "August", not "the last 47 days", so an explicit range is the
    honest interface and the HTTP API already took one. A bare date on ``--to`` covers
    that whole day: asking for `--to 2026-08-17` and silently getting midnight would
    drop a day of evidence from a package someone signs.
    """
    if from_ is None and to is None:
        return dt.datetime.now(dt.UTC) - dt.timedelta(days=since_days), None

    def parse(value: str, *, end_of_day: bool) -> dt.datetime:
        try:
            moment = dt.datetime.fromisoformat(value)
        except ValueError as exc:
            raise typer.BadParameter(
                f"{value!r} is not a date. Use YYYY-MM-DD, or a full ISO-8601 timestamp."
            ) from exc
        if len(value.strip()) == 10 and end_of_day:
            moment = moment.replace(hour=23, minute=59, second=59, microsecond=999999)
        return moment if moment.tzinfo else moment.replace(tzinfo=dt.UTC)

    period_to = parse(to, end_of_day=True) if to is not None else dt.datetime.now(dt.UTC)
    period_from = (
        parse(from_, end_of_day=False)
        if from_ is not None
        else period_to - dt.timedelta(days=since_days)
    )
    if period_from >= period_to:
        raise typer.BadParameter(f"--from ({period_from:%Y-%m-%d}) is not before --to")
    return period_from, period_to


@evidence_app.command("export")
def evidence_export(
    agent: list[str] = typer.Option(None, "--agent", help="Repeatable; default all."),
    from_: str | None = typer.Option(
        None, "--from", help="Start of the period, YYYY-MM-DD or ISO-8601. Default: --since-days."
    ),
    to: str | None = typer.Option(
        None, "--to", help="End of the period, inclusive of a whole day given as YYYY-MM-DD."
    ),
    since_days: int = 30,
    control: list[str] = typer.Option(None, "--control", help="Repeatable; default all."),
    requested_by: str = "cli",
) -> None:
    """Build an auditor-ready evidence package."""
    from agentfox.apps.report import evidence

    period_from, period_to = _evidence_period(from_, to, since_days)
    with _session() as session:
        package = evidence.build(
            session,
            agents=list(agent) if agent else ["*"],
            controls=list(control) if control else ["*"],
            period_from=period_from,
            period_to=period_to,
            requested_by=requested_by,
        )
        path = package.path
        counts = package.manifest_json["counts"]
        valid = package.chain_verification_json.get("valid")

    console.print(f"[green]evidence package[/] {path}")
    covered_to = period_to or dt.datetime.now(dt.UTC)
    console.print(f"  period                   {period_from:%Y-%m-%d} → {covered_to:%Y-%m-%d}")
    for key, value in counts.items():
        console.print(f"  {key.replace('_', ' '):<24} {value}")
    console.print(
        f"  chain verification       "
        f"[{'green' if valid else 'red'}]{'valid' if valid else 'INVALID'}[/]"
    )
    console.print("\n[dim]Verify independently: unzip, then `python3 verify_chain.py`[/]")
