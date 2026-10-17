"""How a static scan's exposure reads in a terminal — shared by `check` and `quickscan`.

Both commands lead with the same thing, so it is written once: the lethal trifecta
first, in a sentence a security owner can forward unedited, then what the agent can
reach (tools and MCP servers) with each one's flags in words rather than codes.
"""

from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

#: The flags as a column of short words. Codes stay in `--json`.
FLAG_WORD = {
    "private_data": "private data",
    "untrusted_input": "untrusted input",
    "exfiltration": "sends out / irreversible",
}


def print_trifectas(console: Console, report: Any) -> None:
    """One red panel per lethal trifecta. Prints nothing when there is none."""
    for site in report.trifectas:
        fix = (site.evidence or {}).get("fix", "")
        console.print(
            Panel(
                f"{site.detail}\n\n[dim]{fix}[/]",
                title="[bold red]CRITICAL · lethal trifecta[/]",
                subtitle="[dim]private data + untrusted content + a way out[/]",
                title_align="left",
                subtitle_align="left",
                border_style="red",
            )
        )


def _flags_text(site: Any) -> str:
    caps = getattr(site, "caps", None)
    if caps is not None and not caps.known:
        return "[yellow]unknown — not classified[/]"
    if not site.capabilities:
        return "[dim]—[/]"
    return ", ".join(FLAG_WORD.get(f, f) for f in site.capabilities)


def surface_line(report: Any) -> str:
    """`4 tools · 2 MCP servers (filesystem, fetch)` — the one-line count."""
    tools = report.tools
    servers = report.mcp_servers
    parts = [f"[bold]{len(tools)}[/] tool{'' if len(tools) == 1 else 's'}"]
    server_text = f"[bold]{len(servers)}[/] MCP server{'' if len(servers) == 1 else 's'}"
    if servers:
        names = [s.name or "?" for s in servers]
        server_text += f" ({', '.join(names[:5])}{', …' if len(names) > 5 else ''})"
    parts.append(server_text)
    return " · ".join(parts)


def print_surface(
    console: Console, report: Any, *, limit: int = 12, more_hint: str = "see --json"
) -> None:
    """What the agent can reach: each tool and MCP server and what it can do."""
    items = report.tools + report.mcp_servers
    console.print(f"  [dim]can reach:[/] {surface_line(report)}")
    if not items:
        return
    table = Table(box=None, padding=(0, 1), show_header=False)
    table.add_column("name", no_wrap=True)
    table.add_column("where", style="dim", no_wrap=True)
    table.add_column("what", overflow="fold")
    for site in items[:limit]:
        label = site.name or site.detail
        if site.kind == "mcp_server":
            label = f"{label} [dim](MCP)[/]"
        table.add_row(f"    {label}", site.file, _flags_text(site))
    console.print(table)
    if len(items) > limit:
        console.print(f"    [dim]… and {len(items) - limit} more ({more_hint})[/]")
