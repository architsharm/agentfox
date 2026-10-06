"""`agentfox report` — the one page for the person who signs off.

Everything the product recorded over a period, said once, in plain language:
what is running, what was stopped and why, what is still only being watched, and
how that lines up against a published threat list (as a labelled draft). Markdown
to the terminal by default; `--format html` for something to forward.
"""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

console = Console()


def report(
    agent: list[str] = typer.Option(
        None, "--agent", "-a", help="Only this agent. Repeat for several. Default: all."
    ),
    since: str = typer.Option("7d", "--since", help="How far back: 24h, 7d, 2w, 30d."),
    fmt: str = typer.Option("md", "--format", "-f", help="md or html."),
    out: Path | None = typer.Option(
        None, "--out", "-o", help="Write to this file instead of printing."
    ),
) -> None:
    """A one-page summary of what your agents did and what was contained."""
    from agentfox.apps.report.summary import (
        build_summary,
        parse_since,
        render_html,
        render_markdown,
    )
    from agentfox.core.db import init_db, session_scope

    fmt = fmt.lower().strip()
    if fmt not in ("md", "markdown", "html"):
        console.print(f"[red]unknown format {fmt!r}[/] — use md or html")
        raise typer.Exit(2)
    try:
        window = parse_since(since)
    except ValueError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(2) from exc

    init_db()
    with session_scope() as session:
        data = build_summary(session, agents=list(agent or []), since=window)
        text = render_html(data) if fmt == "html" else render_markdown(data)

    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text)
        console.print(f"[green]wrote[/] {out}")
        return
    # Plain stdout, not Rich: the output is a document to pipe or paste, and Rich
    # would wrap it at the terminal width and read square brackets as markup.
    typer.echo(text, nl=False)


def register(app: typer.Typer) -> None:
    app.command("report")(report)
