"""`agentfox admin detectors` — see which detectors can run here, and fetch the models some need."""

from __future__ import annotations

import typer
from rich.table import Table

from agentfox.apps.cli.commands._shared import console, dashboard_url

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
    from agentfox.capabilities.detection.models import GatedModel, models_for, pull

    detector = all_detectors().get(key)
    if detector is None and key.startswith("validator."):
        # A validator that only runs as a rule has no detector of its own, and still
        # needs its weights before a rule can use it.
        from agentfox.capabilities.detection.validators import get_validator
        from agentfox.capabilities.detection.validators.detector import ValidatorDetector

        validator = get_validator(key.removeprefix("validator."))
        detector = ValidatorDetector(validator) if validator is not None else None
    if detector is None:
        console.print(f"[red]unknown detector '{key}'[/]")
        raise typer.Exit(1)
    if not models_for(detector):
        console.print(f"{key} uses no model; nothing to download.")
        return
    console.print(_what_downloads(detector))
    try:
        ids = pull(detector)
    except ImportError as exc:
        console.print(
            f"[red]{exc}[/] — install the extra that provides it, e.g. "
            "`pip install 'agentfox[classifiers]'`."
        )
        raise typer.Exit(1) from exc
    except GatedModel as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc
    console.print(f"[green]downloaded[/] {', '.join(ids)}")
    console.print(
        "Restart the gateway (or your app, for agentfox.auto()): an enabled detector "
        "runs from then on. `agentfox admin detectors list` shows which run here."
        + (
            " To switch one on or off: Policies → Checks in the dashboard."
            if dashboard_url()
            else ""
        )
    )


def _what_downloads(detector) -> str:
    """Which models a pull fetches and what each is for: `injection.classifier` fetches
    two, and the command used to download both without a word about the second."""
    from agentfox.capabilities.detection.models import models_for

    ids = models_for(detector)
    primary = getattr(detector, "model_id", None)
    secondary = getattr(detector, "secondary_model_id", None)
    if len(ids) == 1:
        return f"Downloading {ids[0]} for {detector.key}."
    lines = [f"Downloading {len(ids)} models for {detector.key}:"]
    for model_id in ids:
        if model_id == primary:
            role = "the model it checks with"
        elif model_id == secondary:
            role = (
                "a second opinion, asked only when the first finds nothing; its hits are "
                "recorded, never blocked on"
            )
        else:
            role = "used alongside it"
        lines.append(f"  {model_id}: {role}")
    return "\n".join(lines)
