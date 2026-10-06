"""`agentfox hooks` — the warm daemon and the thin per-call hook for coding agents."""

from __future__ import annotations

import sys
from pathlib import Path

import typer

from agentfox.cli.commands._shared import _session, console

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
    import json as _json

    from agentfox.hooks import DaemonUnavailable, client
    from agentfox.hooks import harness as harness_mod

    raw = sys.stdin.read()
    try:
        payload = _json.loads(raw or "{}")
    except _json.JSONDecodeError as exc:
        # Exit 0: a hook that cannot parse its input must not take the agent
        # down with it. It says so on stderr, where the harness shows it.
        print(f"agentfox: could not parse the hook payload: {exc}", file=sys.stderr)
        raise typer.Exit(0) from exc

    try:
        call = harness_mod.parse(harness, payload)
    except harness_mod.UnknownHarness as exc:
        print(f"agentfox: {exc}", file=sys.stderr)
        raise typer.Exit(0) from exc

    slug = agent or call.session_id or "unknown"
    try:
        if call.checks_content:
            # PostToolUse and UserPromptSubmit carry text, not a call to
            # authorise. Same daemon, same policy set, different surface —
            # which is what makes nine surfaces a real claim at a hook rather
            # than an architecture diagram.
            if not call.content.strip():
                # Nothing to check. Say nothing rather than run the engine over
                # an empty string and record a decision about it.
                print("{}")
                return
            verdict = client.guard_content(
                agent=slug,
                surface=call.surface,
                content=call.content,
                tool=call.tool,
            )
        else:
            verdict = client.guard_tool_call(
                agent=slug,
                tool=call.tool,
                arguments=call.arguments,
            )
    except DaemonUnavailable as exc:
        client.report_unavailable(exc)
        raise typer.Exit(0) from exc

    print(_json.dumps(harness_mod.render(harness, call, verdict)))


@hooks_app.command("install")
def hooks_install(
    harness: str = typer.Option("claude", "--harness"),
    agent: str = typer.Option(..., "--agent", help="Agent slug these calls are governed as."),
    path: Path = typer.Option(Path("."), "--path", help="Project to install into."),
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

    from agentfox.hooks import capability
    from agentfox.hooks import harness as harness_mod

    if harness not in harness_mod.known_harnesses():
        known = ", ".join(harness_mod.known_harnesses())
        console.print(f"[red]no adapter for {harness!r}[/] — known: {known}")
        raise typer.Exit(1)

    settings = path / ".claude" / "settings.json"
    command = f"agentfox hooks run --harness {harness} --agent {agent}"
    # Three events, because one event is one surface. PreToolUse sees
    # arguments, PostToolUse sees results — the canonical indirect-injection
    # vector, and the one a tool-call-only hook is blind to — and
    # UserPromptSubmit sees the turn. `matcher` is a tool-name filter and the
    # two non-tool events do not take one.
    events = _hook_events(harness)
    block = {
        "hooks": {
            event: [
                {"matcher": "*", "hooks": [{"type": "command", "command": command}]}
                if event.endswith("ToolUse")
                else {"hooks": [{"type": "command", "command": command}]}
            ]
            for event in events
        }
    }

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
    from agentfox.hooks.baseline import install_baseline

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

    settings.parent.mkdir(parents=True, exist_ok=True)
    existing = {}
    if settings.exists():
        try:
            existing = _json.loads(settings.read_text())
        except _json.JSONDecodeError:
            console.print(f"[red]{settings} is not valid JSON[/] — not overwriting it.")
            raise typer.Exit(1) from None
    added = []
    for event, entries in block["hooks"].items():
        hooks = existing.setdefault("hooks", {}).setdefault(event, [])
        if any(command in _json.dumps(entry) for entry in hooks):
            continue
        hooks.extend(entries)
        added.append(event)
    # Before the early return, so re-running install on an existing hook also
    # repairs a pack binding an older version left wildcarded.
    _enable_coding_pack(agent)
    if not added:
        console.print("\n  [dim]already installed.[/]")
        return
    settings.write_text(_json.dumps(existing, indent=2) + "\n")
    console.print(f"\n  [green]written[/] {settings} [dim]({', '.join(added)})[/]")


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


def _hook_events(harness: str) -> list[str]:
    """Which events we have an adapter for, in the order they fire.

    Read off the capability table rather than hard-coded, so an event nobody
    has established anything about cannot be installed by accident — and so
    adding one is a row plus an adapter branch, not an edit here.
    """
    from agentfox.hooks.capability import EVENT_SURFACE

    order = {"UserPromptSubmit": 0, "PreToolUse": 1, "PostToolUse": 2}
    events = [event for (h, event) in EVENT_SURFACE if h == harness]
    return sorted(events, key=lambda e: (order.get(e, 99), e))


def client_daemon_running() -> bool:
    from agentfox.hooks import ping

    return ping()


@hooks_app.command("status")
def hooks_status() -> None:
    """Is the daemon up, and does a deny on this harness actually stop anything?"""
    from agentfox.hooks import capability, ping, socket_path

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
