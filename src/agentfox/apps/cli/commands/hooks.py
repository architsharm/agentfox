"""`agentfox hooks` — the warm daemon and the thin per-call hook for coding agents."""

from __future__ import annotations

import sys
from pathlib import Path

import typer

from agentfox.apps.cli.commands._shared import _session, console

#: The harness `hooks install` assumes when --harness is not given.
DEFAULT_HARNESS = "claude"

hooks_app = typer.Typer(
    help="Run AgentFox where the agent already is: a warm daemon and a thin per-call hook.",
    no_args_is_help=True,
)


@hooks_app.command("daemon")
def hooks_daemon(
    socket: Path | None = typer.Option(None, "--socket", help="Override the socket path."),
) -> None:
    """Run the warm process a hook talks to.

    A harness spawns its hook as a fresh process per tool call, and importing
    AgentFox costs seconds — measured here at 3.9s on the first call against a
    cold daemon, then 6ms once warm. That gap is the whole reason this exists:
    a hook that costs two seconds a call is a hook the operator removes.
    """
    from agentfox.hooks import HookDaemon
    from agentfox.hooks.daemon import warm

    daemon = HookDaemon(socket)
    console.print("[bold]AgentFox hook daemon[/]")
    console.print(f"  socket   [dim]{daemon.path}[/]")
    with console.status("warming detectors and the database…"):
        warm()
    daemon.start()
    console.print("  [green]ready[/]  [dim]ctrl-c to stop[/]")
    try:
        daemon.serve_forever()
    except KeyboardInterrupt:
        console.print("\n  stopping")
    finally:
        daemon.stop()


@hooks_app.command("run")
def hooks_run(
    harness: str = typer.Option(..., "--harness", help="Which harness is calling."),
    agent: str = typer.Option("", "--agent", help="Agent slug to govern this session as."),
) -> None:
    """The per-call hook. Reads the harness payload on stdin, writes its reply.

    Everything in this path runs in a process the harness creates and destroys
    per tool call, so it does the least possible: parse, ask the daemon, print.
    Measured against a warm daemon, the round trip is about 6ms; the same work
    without one is 3.9 seconds, because `import agentfox` is.
    """
    from agentfox.hooks.run import run

    out = run(harness, agent, sys.stdin.read())
    if out.stderr:
        print(out.stderr, file=sys.stderr)
    if out.stdout:
        print(out.stdout)
    if out.exit_code:
        raise typer.Exit(out.exit_code)


@hooks_app.command("install")
def hooks_install(
    harness: str | None = typer.Option(
        None,
        "--harness",
        help="Which harness to install for: claude (Claude Code) or codex (Codex CLI). "
        "Default: claude.",
    ),
    agent: str = typer.Option(..., "--agent", help="Agent slug these calls are governed as."),
    path: Path = typer.Option(Path("."), "--path", help="Project to install into."),
    scope: str = typer.Option(
        "project",
        "--scope",
        help="Where the hook configuration goes: project (this repository), local (Claude "
        "Code's settings.local.json; the project file for Codex) or user (your home "
        "directory, every project).",
    ),
    write: bool = typer.Option(False, "--write", help="Actually write the settings file."),
    environment: str | None = typer.Option(
        None,
        "--env",
        help="Environment the agent runs in. Default: development for a new agent; an "
        "agent already registered keeps its own.",
    ),
    grant: bool = typer.Option(
        True,
        "--grant/--no-grant",
        help="Grant the harness's built-in tools to the agent (the default), so ordinary "
        "work is not refused by default-deny.",
    ),
) -> None:
    """Show, or write, the hook configuration for a harness.

    Dry by default. This edits a file that decides whether the operator's agent
    runs at all, so it prints what it would do and waits to be told twice.

    With --write it also sets up a working baseline: the agent is registered
    (development unless --env says otherwise), the harness's built-in tools are
    declared with their real impact and granted to it, and the coding-agent pack is
    bound to it in observe. Destructive commands are still refused.
    """
    import json as _json

    from agentfox import harnesses
    from agentfox.harnesses import capability

    if harness is None:
        # Claude Code was the only harness for long enough that every existing command
        # line omits --harness; it stays the default rather than becoming an error.
        harness = DEFAULT_HARNESS
    if scope not in ("project", "local", "user"):
        console.print(f"[red]--scope must be project, local or user[/], not {scope!r}")
        raise typer.Exit(1)
    try:
        adapter = harnesses.get(harness)
    except harnesses.UnknownHarness:
        known = ", ".join(harnesses.known())
        console.print(f"[red]no adapter for {harness!r}[/] — known: {known}")
        raise typer.Exit(1) from None

    # One block per event, because one event is one surface. On Claude Code:
    # PreToolUse sees arguments, PostToolUse sees results — the canonical
    # indirect-injection vector, and the one a tool-call-only hook is blind to —
    # and UserPromptSubmit sees the turn. The adapter decides the file and its shape.
    settings, block = adapter.preview(path, scope, agent=agent)  # type: ignore[arg-type]
    events = list(adapter.events.values())

    console.print(f"  [bold]{settings}[/]")
    console.print(f"[dim]{_json.dumps(block, indent=2)}[/]")

    # The honest line per event, and the reason the capability table exists.
    # These differ, and reporting them as one would be the exact overclaim
    # capability.py was written to stop: a deny on PreToolUse stops the call,
    # and a deny on PostToolUse does not, because the call has already run.
    console.print("")
    for event in events:
        console.print(f"  {capability.describe(harness, event)}")
        if not capability.capability_of(harness, event):
            console.print(
                f"  [yellow]{event} will record and must not be relied on to stop "
                "anything[/] until that is probed."
            )
    for note in getattr(adapter, "install_notes", ()):
        console.print(f"  [yellow]{adapter.display_name}:[/] {note}")
    console.print(
        "\n  [dim]A hook governs the agent on this machine. It is not a boundary: "
        "anything not going through this harness is not going through this.[/]"
    )

    if not write:
        console.print("\n  [dim]Nothing written. Re-run with --write.[/]")
        return
    if not client_daemon_running():
        console.print(
            "\n  [yellow]The daemon is not running[/] — every call will report "
            "unchecked until `agentfox admin hooks daemon` is up."
        )
    # The working baseline. Without it the hook refused everything: the agent was
    # a production shadow with no grants, so `ls` hit capability default-deny and
    # every shell command `action.production_irreversible`.
    from agentfox.harnesses.baseline import install_baseline

    with _session() as session:
        baseline = install_baseline(
            session, harness=harness, agent_slug=agent, environment=environment, grant=grant
        )
    if baseline.registered:
        console.print(
            f"  [green]registered[/] {baseline.agent} [dim](environment {baseline.environment})[/]"
        )
    elif baseline.environment_changed:
        console.print(f"  [green]environment[/] {baseline.agent} → {baseline.environment}")
    if baseline.tools_declared:
        console.print(
            f"  [green]declared[/] {len(baseline.tools_declared)} {harness} tool(s) in the registry"
        )
    if baseline.tools_granted:
        console.print(
            f"  [green]granted[/] {', '.join(baseline.tools_granted)} to {baseline.agent} "
            "[dim](review with `agentfox permit list`; revoke with `agentfox permit revoke`)[/]"
        )
    elif not grant:
        console.print(
            "  [yellow]no grants[/] — capability default-deny refuses every tool until you "
            f"grant them (`agentfox permit grant {baseline.agent} <tool>`)"
        )
    console.print(
        "  [dim]Other tools (MCP servers, anything the harness adds) have no grant: "
        f"`agentfox policy proposals from-traffic --agent {baseline.agent}` proposes them "
        "from what the agent was seen to call.[/]"
    )

    from agentfox.harnesses.base import InstallError

    try:
        changes = adapter.install(path, scope, agent=agent)  # type: ignore[arg-type]
    except InstallError as exc:
        console.print(f"[red]{exc}[/] — not overwriting it.")
        raise typer.Exit(1) from None
    # Before the early return, so re-running install on an existing hook also
    # repairs a pack binding an older version left wildcarded.
    _enable_coding_pack(agent)
    added = [change for change in changes if change.action != "unchanged"]
    if not added:
        console.print("\n  [dim]already installed.[/]")
        return
    for change in added:
        backed_up = change.backup and change.path.is_file()
        change.apply()
        console.print(f"\n  [green]written[/] {change.path} [dim]({', '.join(change.events)})[/]")
        if backed_up:
            console.print(f"  [dim]previous file kept as {change.backup_path}[/]")


def _enable_coding_pack(agent: str) -> None:
    """A hooked agent is a coding agent: bind the pack tuned for one, to it alone."""
    from agentfox.platform.policy.coding import enable_for_agent

    with _session() as session:
        covered = enable_for_agent(session, agent)
    if covered:
        console.print(
            f"  [green]coding-agent[/] pack applies to {', '.join(covered)} "
            "[dim](it ships in observe; `agentfox policy enforce coding-agent` to block)[/]"
        )


def client_daemon_running() -> bool:
    from agentfox.hooks import ping

    return ping()


@hooks_app.command("status")
def hooks_status() -> None:
    """Is the daemon up, and does a deny on this harness actually stop anything?"""
    from agentfox.harnesses import capability
    from agentfox.hooks import ping, socket_path

    path = socket_path()
    up = ping()
    console.print(f"  socket    [dim]{path}[/]")
    console.print(f"  daemon    {'[green]listening[/]' if up else '[red]not running[/]'}")
    if not up:
        console.print("            [dim]start it with `agentfox admin hooks daemon`[/]")

    console.print(f"\n  verified harness events: {len(capability.CAPABILITY)}")
    if not capability.CAPABILITY:
        # The honest state, and said as a fact rather than a gap to apologise
        # for. A table filled with plausible values would be worse than empty.
        console.print(
            "  [dim]None yet. Whether a deny stops a call is a property of each\n"
            "  harness's own wire contract, and this table only holds rows somebody\n"
            "  has probed. Until then a hook observes and records; it does not\n"
            "  promise to block.[/]"
        )
        return
    for (harness, event), row in sorted(capability.CAPABILITY.items()):
        console.print(
            f"  {harness}/{event}: {row.capability}  [dim]{row.evidence} {row.version}[/]"
        )
