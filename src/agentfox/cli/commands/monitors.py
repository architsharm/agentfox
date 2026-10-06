"""`agentfox scan monitors` and `agentfox admin jobs` — watch sources unattended.

`scan monitors` lists, adds, pauses, resumes, removes and runs monitors of connected
sources (GitHub repositories, hosted-API specs, MCP servers) in this deployment's
database. `admin jobs run-due` is the job runner a self-hosted deployment puts on its
own scheduler: the same pass `/api/internal/jobs/run` makes for the hosted cron.
"""

from __future__ import annotations

import re
from typing import Any

import typer
from rich.table import Table

from agentfox.cli.commands._shared import _emit, _session, console

monitors_app = typer.Typer(
    help="Watch connected sources on a schedule: list, add, pause, resume, remove, run.",
    no_args_is_help=True,
)
jobs_app = typer.Typer(
    help="Run scheduled work: monitors, drift, compliance, canaries.", no_args_is_help=True
)

_DURATION = re.compile(r"^\s*(\d+)\s*([smhd]?)\s*$", re.I)
_UNITS = {"": 1, "s": 1, "m": 60, "h": 3600, "d": 86400}


def parse_interval(text: str) -> int:
    """`90`, `30m`, `6h`, `1d` -> seconds."""
    match = _DURATION.match(text or "")
    if not match:
        raise typer.BadParameter("use seconds or a number with s, m, h or d (e.g. 6h)")
    return int(match.group(1)) * _UNITS[match.group(2).lower()]


def _find(session: Any, ident: str):
    from sqlalchemy import or_, select

    from agentfox.core.models import Monitor

    monitor = session.get(Monitor, ident) or session.scalar(
        select(Monitor).where(or_(Monitor.target == ident, Monitor.name == ident))
    )
    if monitor is None:
        console.print(f"[red]no monitor[/] '{ident}' — see [cyan]agentfox scan monitors list[/]")
        raise typer.Exit(2)
    return monitor


def _flush_alerts() -> None:
    """A CLI process exits right after the command: let queued alerts leave first."""
    from agentfox.core import webhooks
    from agentfox.monitoring import alerts

    alerts.wait_for_delivery(10)
    webhooks.wait_for_delivery(10)


def _every(seconds: int) -> str:
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
        if seconds >= size and seconds % size == 0:
            return f"{seconds // size}{unit}"
    return f"{seconds}s"


def _when(value: str | None) -> str:
    return value.replace("T", " ")[:16] if value else "now"


@monitors_app.command("list")
def list_monitors(as_json: bool = typer.Option(False, "--json", help="Print JSON.")) -> None:
    """Every monitor, its last outcome, and when it runs next."""
    from sqlalchemy import select

    from agentfox.core.models import Monitor
    from agentfox.monitoring.service import monitor_json

    with _session() as session:
        rows = [
            monitor_json(m)
            for m in session.scalars(select(Monitor).order_by(Monitor.kind, Monitor.target))
        ]
    if as_json:
        _emit({"monitors": rows}, True)
        return
    if not rows:
        console.print(
            "[dim]No monitors yet.[/] Connecting a repo or registering an MCP server creates one; "
            "or [cyan]agentfox scan monitors add github_repo owner/repo[/]."
        )
        return
    table = Table(show_edge=False, pad_edge=False)
    for column in ("id", "kind", "target", "every", "status", "next run"):
        table.add_column(column)
    for row in rows:
        status = row["status"] if row["enabled"] else f"paused ({row['status']})"
        table.add_row(
            row["id"],
            row["kind"],
            row["target"],
            _every(row["interval_seconds"]),
            status,
            _when(row["next_run_at"]) if row["enabled"] else "—",
        )
    console.print(table)


@monitors_app.command("add")
def add_monitor(
    kind: str = typer.Argument(..., help="github_repo, hosted_api or mcp_server."),
    target: str = typer.Argument(..., help="owner/repo, the spec URL, or the MCP server name."),
    every: str = typer.Option("", "--every", help="Interval, e.g. 30m, 6h, 1d. Default per kind."),
    name: str = typer.Option("", "--name", help="A label for lists and alerts."),
) -> None:
    """Start watching a source. Its first run stores a baseline; later runs report changes."""
    from agentfox.monitoring.service import ensure_monitor, get_monitor

    with _session() as session:
        if get_monitor(session, kind, target) is not None:
            console.print(f"[yellow]already monitored:[/] {kind} {target}")
            raise typer.Exit(1)
        try:
            monitor, _ = ensure_monitor(
                session,
                kind=kind,
                target=target,
                name=name,
                interval_seconds=parse_interval(every) if every else None,
                created_by="cli",
            )
        except ValueError as exc:
            console.print(f"[red]{exc}[/]")
            raise typer.Exit(2) from exc
        console.print(
            f"[green]monitoring[/] {kind} [bold]{target}[/] every "
            f"{_every(monitor.interval_seconds)}  [dim]{monitor.id}[/]"
        )


def _set_enabled(ident: str, enabled: bool) -> None:
    with _session() as session:
        monitor = _find(session, ident)
        monitor.enabled = enabled
        console.print(
            f"{'resumed' if enabled else 'paused'} {monitor.kind} [bold]{monitor.target}[/]"
        )


@monitors_app.command("pause")
def pause_monitor(ident: str = typer.Argument(..., help="Monitor id or target.")) -> None:
    """Stop scheduled runs. Open findings stay open."""
    _set_enabled(ident, False)


@monitors_app.command("resume")
def resume_monitor(ident: str = typer.Argument(..., help="Monitor id or target.")) -> None:
    """Resume scheduled runs."""
    _set_enabled(ident, True)


@monitors_app.command("remove")
def remove_monitor(ident: str = typer.Argument(..., help="Monitor id or target.")) -> None:
    """Stop watching a source. Its findings are kept."""
    with _session() as session:
        monitor = _find(session, ident)
        console.print(f"removed {monitor.kind} [bold]{monitor.target}[/]")
        session.delete(monitor)


@monitors_app.command("run")
def run_monitors(
    ident: str = typer.Argument("", help="Monitor id or target. Omit to run every due monitor."),
    as_json: bool = typer.Option(False, "--json", help="Print JSON."),
) -> None:
    """Run one monitor now, or every monitor that is due."""
    from agentfox.cli._style import SEVERITY_COLOUR
    from agentfox.core.models import Finding, Monitor
    from agentfox.monitoring.service import run_due, run_monitor

    lines: list[str] = []
    with _session() as session:
        if ident:
            results = [run_monitor(session, _find(session, ident), trigger="manual")]
        else:
            results = run_due(session)["results"]
        for result in results:
            monitor = session.get(Monitor, result["monitor_id"])
            head = f"{monitor.kind} [bold]{monitor.target}[/]: {result.get('status')}"
            if result.get("error"):
                head += f"  [red]{result['error']}[/]"
            lines.append(head)
            for key, mark in (
                ("findings_opened", "+"),
                ("findings_reopened", "+"),
                ("findings_closed", "-"),
            ):
                for finding_id in result.get(key) or []:
                    finding = session.get(Finding, finding_id)
                    colour = SEVERITY_COLOUR.get(finding.severity, "dim")
                    lines.append(
                        f"  {mark} [{colour}]{finding.severity}[/] {finding.title}"
                        + ("  [dim](cleared)[/]" if mark == "-" else "")
                    )
    _flush_alerts()
    if as_json:
        _emit({"results": results}, True)
        return
    if not results:
        console.print("[dim]no monitor is due[/]")
    for line in lines:
        console.print(line)


@jobs_app.command("run-due")
def jobs_run_due(
    limit: int = typer.Option(50, "--limit", help="Most jobs to run in this pass."),
    as_json: bool = typer.Option(False, "--json", help="Print JSON."),
) -> None:
    """One pass of the job runner: enqueue due schedules, recover stuck jobs, run them.

    Put this on a scheduler (cron, a systemd timer, a Kubernetes CronJob) every 10-30
    minutes on a self-hosted deployment. Safe to run as often as you like.
    """
    from agentfox.jobs import handlers as _registers_kinds  # noqa: F401
    from agentfox.jobs.scheduler import run_due

    with _session() as session:
        result = run_due(session, limit=limit)
    _flush_alerts()
    if as_json:
        _emit(result, True)
        return
    console.print(
        f"scheduled {result['scheduled']}, ran {result['processed']}, "
        f"recovered {result['recovered']}"
        + ("" if result["scheduler_enabled"] else "  [yellow](scheduler disabled)[/]")
    )
