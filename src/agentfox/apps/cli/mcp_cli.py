"""`agentfox mcp`: expose the observe half of the product to AI clients over MCP.

`serve` speaks the protocol on stdin/stdout, so it must print nothing else to stdout.
`tools` is for people: which tools a connected assistant gets, and what each one does.
"""

from __future__ import annotations

import typer


def serve() -> None:
    """Serve MCP over stdio (for Claude Code, Claude Desktop and other MCP clients).

    Read-only by design: nothing that changes enforcement or stops an agent is exposed.
    """
    from agentfox.apps.mcp_server import serve as serve_stdio

    raise typer.Exit(serve_stdio())


def tools() -> None:
    """List the tools an MCP client gets, with a one-line description of each."""
    from agentfox.apps.mcp_server import TOOLS

    width = max(len(name) for name in TOOLS)
    for tool in TOOLS.values():
        summary = tool.description.split(". ")[0].rstrip(".")
        typer.echo(f"{tool.name:<{width}}  {summary}")


def register(app: typer.Typer) -> None:
    mcp_app = typer.Typer(
        help="Model Context Protocol server: read-only governance tools for AI clients.",
        no_args_is_help=True,
    )
    mcp_app.command(name="serve")(serve)
    mcp_app.command(name="tools")(tools)
    app.add_typer(mcp_app, name="mcp")
