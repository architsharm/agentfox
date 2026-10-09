"""`agentfox admin detectors` — see which detectors can run here, and fetch the models some need."""

from __future__ import annotations

import typer
from rich.table import Table

from agentfox.apps.cli.commands._shared import console

detectors_app = typer.Typer(
    help="See which detectors can run here, and download the models some of them need.",
    no_args_is_help=True,
)


@detectors_app.command("list")
def detectors_list() -> None:
    """Every detector, whether it can run here, and what it needs if not."""
    from agentfox.capabilities.detection import all_detectors
    from agentfox.capabilities.detection.models import models_for, pull_hint

    table = Table(box=None, pad_edge=False)
    for column in ("detector", "ready", "model", "to enable"):
        table.add_column(column)
    for key, detector in sorted(all_detectors().items()):
        ready = detector.available()
        table.add_row(
            key,
            "[green]yes[/]" if ready else "[yellow]no[/]",
            ", ".join(models_for(detector)) or "—",
            ""
            if ready
            else (pull_hint(detector) or getattr(detector, "package", "") or "see docs"),
        )
    console.print(table)


@detectors_app.command("pull")
def detectors_pull(key: str) -> None:
    """Download the model weights a detector loads, so it can run without a network."""
    from agentfox.capabilities.detection import all_detectors
    from agentfox.capabilities.detection.models import models_for, pull

    detector = all_detectors().get(key)
    if detector is None:
        console.print(f"[red]unknown detector '{key}'[/]")
        raise typer.Exit(1)
    if not models_for(detector):
        console.print(f"{key} uses no model; nothing to download.")
        return
    try:
        ids = pull(detector)
    except ImportError as exc:
        console.print(
            f"[red]{exc}[/] — install the extra that provides it, e.g. "
            "`pip install 'agentfox[classifiers]'`."
        )
        raise typer.Exit(1) from exc
    console.print(f"[green]downloaded[/] {', '.join(ids)}")
    console.print("Restart the gateway, then switch it on in Policies → Library → Detectors.")
