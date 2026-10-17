"""`agentfox admin jobs` — run scheduled work unattended.

`admin jobs run-due` is the job runner a self-hosted deployment puts on its own
scheduler: the same pass `/api/internal/jobs/run` makes for the hosted cron. (`scan
monitors`, the monitors themselves, is AgentFox Enterprise.)
"""

from __future__ import annotations

import typer

from agentfox.apps.cli.commands._shared import _emit, _session, console


def _flush_alerts() -> None:
    """A CLI process exits right after the command: let queued alerts leave first."""
    from agentfox.core import extensions, webhooks

    flush_monitor_alerts = extensions.service("alerts.wait_for_delivery")
    if flush_monitor_alerts is not None:
        flush_monitor_alerts(10)
    webhooks.wait_for_delivery(10)


jobs_app = typer.Typer(
    help="Run scheduled work: monitors, drift, compliance, canaries.", no_args_is_help=True
)


@jobs_app.command("run-due")
def jobs_run_due(
    limit: int = typer.Option(50, "--limit", help="Most jobs to run in this pass."),
    as_json: bool = typer.Option(False, "--json", help="Print JSON."),
) -> None:
    """One pass of the job runner: enqueue due schedules, recover stuck jobs, run them.

    Put this on a scheduler (cron, a systemd timer, a Kubernetes CronJob) every 10-30
    minutes on a self-hosted deployment. Safe to run as often as you like.
    """
    from agentfox.apps import jobs as _registers_kinds  # noqa: F401
    from agentfox.platform.jobs.scheduler import run_due

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
