"""`agentfox up`: from nothing to a governed project, in one command.

    agentfox up                  # asks, with a recommended answer for every question
    agentfox up --yes            # takes the recommended answers (CI, scripts)
    agentfox up --target cloud --api-url … --api-token …

Scan, then a handful of questions (where it runs, what to include, how strict to
start, plus a follow-up or two per choice), then a plan to confirm, then everything
is done in one pass. Each step reuses what the single-purpose commands do (`init`,
`admin hooks install`, `declare tool`, `scan --submit`, the monitors), so `up` is a
faster way in, not a second implementation. Answers are saved in `.agentfox/up.json`
(credentials in `.agentfox/agentfox.env`, 0600, git-ignored), so running it again
offers the same choices and only changes what is new.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel

from agentfox.apps.cli.wizard.components import (
    BY_KEY,
    CATALOGUE,
    MODES,
    Run,
    apply_mode,
    plural,
)
from agentfox.apps.cli.wizard.detect import (
    ANSWERS_FILE,
    ENV_FILE,
    STATE_DIR,
    Context,
    detect,
    save_answers,
    slugify,
    write_env,
)
from agentfox.apps.cli.wizard.prompt import Choice, Interactive, Prompter, Scripted
from agentfox.apps.cli.wizard.targets import TargetError, choose

console = Console()

#: Components that act as an agent, and so need its name.
_NAMED = ("coding-agents", "python-app", "gateway")


def _keys(raw: str | None, option: str) -> set[str]:
    keys = {k.strip() for k in (raw or "").split(",") if k.strip()}
    unknown = keys - set(BY_KEY)
    if unknown:
        raise typer.BadParameter(
            f"unknown: {', '.join(sorted(unknown))}. Known: {', '.join(BY_KEY)}",
            param_hint=option,
        )
    return keys


@dataclass
class Pick:
    """The agent `up` sets up: the name `auto()` runs under, the agent the scan found
    for it (None when the code names none), the system it starts (it and every agent
    it hands work to, by key) and those agents' own tools."""

    name: str
    spec: Any = None
    members: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    #: The file that starts it (or defines it), relative to the project.
    file: str | None = None
    #: How many separate agent systems the project holds: more than one means a
    #: folder of independent examples or apps, and only this one is set up.
    systems: int = 0
    #: The roots of the systems left alone (in other files), best first run first.
    others: list[str] = field(default_factory=list)


def _python_specs(ctx: Any) -> list[Any]:
    return [a for a in ctx.report.agents if a.file.endswith(".py")]


def _rel(ctx: Any, path: Path) -> str:
    try:
        return str(path.relative_to(ctx.root))
    except ValueError:
        return str(path)


def _read(ctx: Any, rel: str) -> str:
    try:
        return (ctx.root / rel).read_text(errors="ignore")
    except OSError:
        return ""


#: Calls that start an agent on the object they are made on: `agent.run_sync(`,
#: `agent.run_stream(`, `crew.kickoff(`, `graph.invoke(`, `team.run_stream(`,
#: `agent.chat(`, `user_proxy.initiate_chat(`.
_RUN_METHOD = (
    r"(?:kickoff|a?invoke|a?stream|astream_events|run|arun|chat|achat|a?_?initiate_chat)\w*"
)


def _visible(spec: Any, name: str, file: str, text: str) -> bool:
    """Whether ``name`` in ``file`` can refer to ``spec``: defined there, or imported
    from the module that defines it. Examples folders reuse names (`spanish_agent` in
    four files); a run site means the one its own file can see."""
    import re

    if spec.file == file:
        return True
    stem = re.escape(Path(spec.file).stem)
    imported = re.search(rf"from\s+[\w.]*\b{stem}\s+import\s+(\([^)]*\)|[^\n]*)", text)
    # The name itself, or the class it lives in (`from crew import TicketTriageCrew`
    # then `TicketTriageCrew().crew().kickoff(`).
    for imported_name in (name, spec.name):
        if imported and imported_name and str(imported_name).isidentifier():
            if re.search(rf"\b{re.escape(imported_name)}\b", imported.group(1)):
                return True
    return bool(re.search(rf"^\s*import\s+[\w.]*\b{stem}\b", text, re.M))


def _started(ctx: Any, specs: list[Any], files: list[str]) -> list[str]:
    """Keys of the agents a run site in ``files`` starts, in the order the code starts
    them: `Runner.run(triage, …)`, `agent.run_stream(…)`, `crew.kickoff(…)`,
    `graph.invoke(…)`, by the variable or attribute the code holds the agent in."""
    import re

    order: dict[str, int] = {}
    for file in files:
        text = _read(ctx, file)
        if not text:
            continue
        for spec in specs:
            for name in dict.fromkeys(n for n in (spec.attr, spec.var) if n):
                if not str(name).isidentifier() or not _visible(spec, name, file, text):
                    continue
                run = re.compile(
                    rf"Runner\.run\w*\(\s*(?:starting_agent\s*=\s*)?{name}\b"
                    rf"|\b{name}\s*(?:\(\s*\))?\s*\.\s*{_RUN_METHOD}\s*\("
                )
                hit = run.search(text)
                if hit and spec.key not in order:
                    order[spec.key] = hit.start() + 10**6 * files.index(file)
    return sorted(order, key=order.__getitem__)


def _name_of(ctx: Any, spec: Any) -> str:
    """The name `auto()` runs under for ``spec``: the scan's key (the code's own name,
    disambiguated only when two agents share it), except for a container the code
    names only by a variable (`builder = create_swarm(...)`, `workflow =
    StateGraph(...)`), which takes its project's name: the members keep theirs."""
    from agentfox.capabilities.discovery.agents import _slug
    from agentfox.capabilities.onboarding.mapper import project_name_for, unnamed_container

    if unnamed_container(spec):
        return slugify(project_name_for(ctx.root, spec.file))
    name = _slug(spec.name or "")
    if spec.key == name or spec.key.startswith(f"{name}-"):
        return spec.key  # the code's name, with the scan's suffix when two share it
    # The scan named it for the code (a hand-written loop takes the project's name).
    return name or spec.key


def _members(ctx: Any, key: str) -> list[str]:
    """``key`` and every agent it hands work to, directly or not."""
    children: dict[str, list[str]] = {}
    for edge in ctx.report.agent_edges:
        children.setdefault(edge.parent, []).append(edge.child)
    out, queue = [key], [key]
    while queue:
        for child in children.get(queue.pop(0), []):
            if child not in out:
                out.append(child)
                queue.append(child)
    return out


def _systems(ctx: Any) -> list[dict[str, Any]]:
    """The independent agent systems: agents joined by any hand-off, either way, are
    one system. Each is ``{"root", "members"}``, the root the agent that hands work to
    the most of it (see `systems_of`), members from it outwards. Deterministic: the
    count is the number of separate systems, never containers plus their members."""
    from agentfox.platform.registry.projects import systems_of

    keys = sorted(a.key for a in _python_specs(ctx))
    known = set(keys)
    edges = [
        (e.parent, e.child, e.relation)
        for e in ctx.report.agent_edges
        if e.parent in known and e.child in known
    ]
    parent = {k: k for k in keys}

    def find(k: str) -> str:
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k

    for a, b, _ in edges:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)
    groups: dict[str, list[str]] = {}
    for k in keys:
        groups.setdefault(find(k), []).append(k)
    rooted = systems_of(keys, edges)
    out = []
    for group in groups.values():
        inside = set(group)
        best = min(
            (sys for sys in rooted if sys["root"] in inside),
            key=lambda sys: (-len(sys["members"]), sys["root"]),
        )
        order = [m["slug"] for m in best["members"]]
        order += [k for k in group if k not in order]
        out.append({"root": best["root"], "members": order})
    return sorted(out, key=lambda sys: sys["root"])


def _singled_out(ctx: Any, entries: list[str]) -> str | None:
    """The entry file the project itself points at, when one does: a file it declares
    (`[project.scripts]`, langgraph.json), or the only file that runs as a script or
    runs an agent. None for a folder of examples where many files do."""
    from agentfox.capabilities.onboarding.project_files import (
        _MAIN_GUARD,
        AGENT_RUN,
        _declared_entries,
        _matches_declared,
    )

    declared = _declared_entries(ctx.root)
    for rel in entries:
        if declared and _matches_declared(rel, declared):
            return rel
    runnable = [
        rel
        for rel in entries
        if _MAIN_GUARD.search(_read(ctx, rel)) or AGENT_RUN.search(_read(ctx, rel))
    ]
    return runnable[0] if len(runnable) == 1 else None


def _ranked_systems(ctx: Any, systems: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Systems best first run first: one with tools of its own and a run site (there
    is something to watch, and something to start), then the most agents and tools,
    then the one nearest the root. A tool-less agent never wins over a system with
    tools."""
    specs = _python_specs(ctx)
    by_key = {a.key: a for a in specs}
    entries = [_rel(ctx, p) for p in ctx.entry_points]
    scored = []
    for system in systems:
        members = [by_key[k] for k in system["members"] if k in by_key]
        tools = {t for a in members for t in a.tools}
        files = list(dict.fromkeys([*(a.file for a in members), *entries]))
        runs = bool(_started(ctx, members, files))
        root = by_key[system["root"]]
        scored.append(
            (
                (
                    not (tools and runs),
                    not tools,
                    not runs,
                    -len(members),
                    -len(tools),
                    root.file.count("/"),
                    system["root"],
                ),
                {**system, "tools": sorted(tools)},
            )
        )
    return [system for _key, system in sorted(scored, key=lambda item: item[0])]


def _pick(ctx: Any, entry: str | None = None, wanted: str | None = None) -> Pick:
    """The agent to set up. ``wanted`` (`--agent`), when it is an agent the scan found,
    is that agent. With an ``entry`` file, the one a run site there starts, then the
    root of a system defined there: the agent that file actually runs. With neither,
    the file the project points at; and in a folder of independent examples where
    nothing does, the system that makes the best first run (:func:`_ranked_systems`)."""
    specs = _python_specs(ctx)
    if not specs:
        return Pick(wanted or ctx.project)
    by_key = {a.key: a for a in specs}
    entries = [_rel(ctx, p) for p in ctx.entry_points]
    systems = _systems(ctx)
    ranked = _ranked_systems(ctx, systems)
    spec = by_key.get(wanted or "")
    singled = None if entry or spec is not None else _singled_out(ctx, entries)
    if spec is None and not entry and not singled and len(systems) > 1:
        spec = by_key[ranked[0]["root"]]
    if spec is None:
        files = [entry] if entry else [singled] if singled else entries[:1]
        started = _started(ctx, specs, files)
        if not started and not entry:
            started = _started(ctx, specs, entries[:3])
            files = entries[:3]
        handed = {e.child for e in ctx.report.agent_edges}
        # Hand-offs are often two-way (a triage agent and the specialists that hand
        # back to it), so "handed to by nobody" can leave no one; the agent that hands
        # to the most others is the one that starts the run.
        hands_to: dict[str, int] = {}
        for edge in ctx.report.agent_edges:
            hands_to[edge.parent] = hands_to.get(edge.parent, 0) + 1
        rank = {key: n for n, key in enumerate(started)}
        spec = sorted(
            specs,
            key=lambda a: (
                a.key not in rank,
                a.file not in files,
                a.file not in entries,
                a.key in handed,
                -hands_to.get(a.key, 0),
                rank.get(a.key, 0),
            ),
        )[0]
    # The file that starts it: an entry point that runs it, or its own file when that
    # runs it (an example script below the top five entry points, or `--agent`).
    candidates = list(dict.fromkeys([*entries, spec.file]))
    system_of = next((s for s in systems if spec.key in s["members"]), None)
    starters = [by_key[k] for k in (system_of or {"members": [spec.key]})["members"]]
    started_in = next((f for f in candidates if spec.key in _started(ctx, [spec], [f])), None)
    started_in = started_in or next((f for f in candidates if _started(ctx, starters, [f])), None)
    by_ranking = spec.key == wanted or (not entry and not singled and len(systems) > 1)
    file = (
        entry
        or started_in
        or (spec.file if by_ranking or spec.file in entries or not entries else entries[0])
    )
    # What runs in that process is this agent's system and any other the same file
    # defines or starts (a generator and the judge beside it): one auto() governs them
    # all, so their tools are this agent's to call. Systems elsewhere are left alone.
    in_process = {spec.file, file}
    started_here = set(_started(ctx, specs, [file])) if file else set()
    members = _members(ctx, spec.key)
    others: list[str] = []
    for system in ranked:
        root = by_key.get(system["root"])
        if root is None or system["root"] in members:
            continue
        if root.file in in_process or started_here & set(system["members"]):
            members += [m for m in system["members"] if m not in members]
        elif spec.key not in system["members"]:
            others.append(system["root"])
    tools = sorted({t for key in members if key in by_key for t in by_key[key].tools})
    return Pick(
        name=wanted or _name_of(ctx, spec),
        spec=spec,
        members=members,
        tools=tools,
        file=file,
        systems=len(systems),
        others=others,
    )


def _follow_file(ctx: Any, pick: Pick, entry: str, agent: str | None, run: Run) -> Pick:
    """The file auto() goes into changed at the question: the agent and its tools are
    the ones that file runs, whatever name was saved. An agent asked for by `--agent`
    is kept; if that file does not run it, that is said, with the one it does run."""
    fresh = _pick(ctx, entry=entry)
    if agent and pick.spec is not None and pick.spec.key == agent:
        if agent not in fresh.members:
            right = fresh.spec.key if fresh.spec is not None else fresh.name
            console.print(
                f"  [yellow]{escape(entry)} does not run {escape(agent)}[/] — it runs "
                f"[bold]{escape(fresh.name)}[/]. Keeping --agent {escape(agent)}; for "
                f"that one: [cyan]agentfox up --agent {escape(right)}[/]"
            )
        return Pick(**{**pick.__dict__, "file": entry})
    if agent:  # a new name of the user's own: keep it, scope it to the file
        fresh.name = agent
    run.agent = fresh.name
    run.system_tools = fresh.tools if fresh.spec is not None else None
    return fresh


def _agent_name(ctx: Any, entry: str | None = None) -> str:
    """The name to run under (see :func:`_pick`): as the scan prints it and `agentfox
    init` registers it, so one agent has one name everywhere. The project's name when
    the code defines none."""
    return _pick(ctx, entry).name


def _step(number: int, title: str) -> None:
    console.print(f"\n[bold cyan]{number}[/] [bold]{title}[/]")


def _print_scan(ctx: Context) -> None:
    report = ctx.report
    calls = len(report.model_calls)
    rows = [
        (
            "model calls",
            f"{calls}"
            + (f" [red]({len(report.ungoverned)} ungoverned)[/]" if report.ungoverned else ""),
        ),
        ("tools", str(len(ctx.tool_names))),
        ("MCP servers", str(len(ctx.mcp_names))),
    ]
    if report.trifectas:
        rows.append(
            (
                "lethal trifecta",
                f"[red]{len(report.trifectas)}[/] — private data, untrusted input and a "
                "way out, together",
            )
        )
    other = {
        k: v for k, v in report.by_kind().items() if k in ("secret", "shell_call", "sql_build")
    }
    if other:
        rows.append(("also", ", ".join(f"{v} {k.replace('_', ' ')}" for k, v in other.items())))
    # The coding agents this project is set up for (its config directory or
    # instructions file, or hooks already installed), not every one on this machine.
    # One installed on this machine only is said as that, not as this project's.
    harnesses = [h.display for h in ctx.harnesses if h.in_repo or h.hooked]
    elsewhere = [h.display for h in ctx.harnesses if h.present and h.display not in harnesses]
    rows.append(
        (
            "coding agents",
            (", ".join(harnesses) or "none set up in this project")
            + (f" [dim](on this machine: {', '.join(elsewhere)})[/]" if elsewhere else ""),
        )
    )
    flagged = [s for s in ctx.skills if s["issues"]]
    if ctx.skills:
        named = ", ".join(s["skill"] for s in flagged[:3])
        issues = f" [red]({len(flagged)} with issues: {named})[/]" if flagged else ""
        rows.append(("skills", f"{len(ctx.skills)}{issues}"))
    machine = ctx.machine
    if machine is not None and machine.configs:
        issues = (
            sum(1 for e in machine.servers for i in e["issues"] if i["severity"] != "info")
            + machine.skill_issues
        )
        clients = sorted({c["client"] for c in machine.configs})
        found = plural(len(machine.servers), "MCP server")
        rows.append(
            (
                "this machine",
                f"{found} across {', '.join(clients)}"
                + (f", [yellow]{plural(issues, 'issue')}[/]" if issues else "")
                + (
                    f", [red]{plural(len(machine.trifectas), 'lethal trifecta')}[/]"
                    if machine.trifectas
                    else ""
                ),
            )
        )
    if report.frameworks:
        rows.append(("built on", ", ".join(report.frameworks)))
    if ctx.github_repo:
        rows.append(("repository", ctx.github_repo))
    console.print(f"  [dim]{report.files_scanned} files in {escape(ctx.root.resolve().name)}/[/]")
    for label, value in rows:
        console.print(f"  {label:<16}{value}")
    if machine is not None and (machine.trifectas or flagged or machine.critical):
        console.print(
            "  [dim]details:[/] [cyan]agentfox scan machine[/], [cyan]agentfox scan skills[/]"
        )


def _short(where: str) -> str:
    """A database URL or address short enough for one line: SQLite as a path under ~."""
    if not where.startswith("sqlite:///"):
        return where
    path = where.removeprefix("sqlite:///")
    home = str(Path.home())
    path = "~" + path[len(home) :] if path.startswith(home) else path
    if len(path) > 60:
        path = "…/" + "/".join(Path(path).parts[-2:])
    return f"SQLite {path}"


def _hidden(component: Any, run: Run) -> bool:
    """An Enterprise component this control plane does not have: left off the list
    (`--with` still names why), and mentioned once at the end instead."""
    return component.enterprise and component.key not in run.edition.features


def _choices(run: Run) -> list[Choice]:
    out = []
    for component in CATALOGUE:
        if _hidden(component, run):
            continue
        reason = component.unavailable(run)
        out.append(
            Choice(component.key, component.label, "" if reason else component.note(run), reason)
        )
    return out


def up(
    path: Path = typer.Argument(Path("."), help="The project to set up. Default: here."),
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Take the recommended (or last saved) answer to every question."
    ),
    target: str | None = typer.Option(
        None, "--target", help="local, self-hosted or cloud. Asked when omitted."
    ),
    include: str | None = typer.Option(
        None, "--with", help=f"Components to include, comma-separated: {', '.join(BY_KEY)}."
    ),
    exclude: str | None = typer.Option(None, "--without", help="Components to leave out."),
    mode: str | None = typer.Option(
        None, "--mode", help="observe (block nothing yet), defaults, or enforce."
    ),
    agent: str | None = typer.Option(
        None,
        "--agent",
        help="The agent to set up: one the scan found (its file gets auto()), or a new name. "
        "Default: the agent the entry file runs.",
    ),
    api_url: str | None = typer.Option(
        None,
        "--api-url",
        # The names auto() reads first, then the older CLI names.
        envvar=["AGENTFOX_URL", "AGENTFOX_API_URL"],
        help="Gateway address, for self-hosted or cloud.",
    ),
    api_token: str | None = typer.Option(
        None,
        "--api-token",
        envvar=["AGENTFOX_API_KEY", "AGENTFOX_API_TOKEN"],
        help="API key, for self-hosted or cloud.",
    ),
    email: str | None = typer.Option(
        None, "--email", help="First operator's email, when `up` starts a self-hosted stack."
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Ask, show the plan, change nothing."),
    start: bool = typer.Option(
        True, "--start/--no-start", help="Start the hook daemon and local API in the background."
    ),
    skip_machine: bool = typer.Option(
        False,
        "--skip-machine",
        help="Skip the user-level MCP configs and skills of the AI tools on this machine.",
    ),
) -> None:
    """Set up AgentFox for this project: scan, choose, and it does the rest.

    Asks where AgentFox runs (this machine, your own server, or AgentFox Cloud), what
    to cover (coding agents, your Python agent, the gateway, tools, MCP servers,
    monitoring, compliance, the dashboard) and how strict to start, then does all of
    it. Every question has a recommended answer; `--yes` takes them all. Run it again
    any time: it remembers the answers and only changes what is new.
    """
    from agentfox import __version__

    root = Path(path)
    if not root.is_dir():
        console.print(f"[red]{escape(str(path))} is not a directory[/]")
        raise typer.Exit(2)
    if mode is not None and mode not in {m.key for m in MODES}:
        raise typer.BadParameter("choose observe, defaults or enforce", param_hint="--mode")
    wanted, unwanted = _keys(include, "--with"), _keys(exclude, "--without")

    interactive = not yes and sys.stdin.isatty()
    prompter: Prompter = Interactive(console) if interactive else Scripted(console)
    console.print(
        Panel.fit(
            f"[bold]AgentFox setup[/]  [dim]v{__version__}[/]\n"
            "[dim]Scan → choose → done. Every question has a recommended answer: press Enter.[/]",
            border_style="cyan",
        )
    )
    if not interactive and not yes:
        console.print("  [dim]not a terminal: taking the recommended answers (as --yes)[/]")

    # 1. Scan ---------------------------------------------------------------------
    _step(1, "Scan")
    with console.status("reading the repository (nothing is imported or run)…"):
        ctx = detect(root, machine=not skip_machine)
    _print_scan(ctx)
    saved = ctx.saved

    # 2. Where --------------------------------------------------------------------
    _step(2, "Where AgentFox runs")
    try:
        chosen = choose(
            ctx,
            prompter,
            console,
            target=target,
            api_url=api_url,
            api_token=api_token,
            email=email,
            start=start and not dry_run,
        )
    except TargetError as exc:
        console.print(f"  [red]✗[/] {escape(str(exc))}")
        raise typer.Exit(1) from None
    if chosen.key == "local" and not dry_run:
        from agentfox.apps.cli.onboarding import setup_workspace

        setup_workspace(root, saved.get("environment", "development"), brief=True)

    # `--agent` names one the scan found (set that one up) or a new name; a saved name
    # is kept. Either way the agent and the tools it is granted are the ones the chosen
    # file runs (see `_pick`), not every agent in the folder.
    saved_entry = saved.get("entry_point")
    pick = _pick(
        ctx,
        entry=saved_entry if saved_entry and saved_entry != "none" and not agent else None,
        wanted=agent or saved.get("agent"),
    )
    run = Run(
        ctx=ctx,
        target=chosen,
        prompter=prompter,
        console=console,
        agent=pick.name,
        start=start,
        interactive=interactive,
    )
    run.system_tools = pick.tools if pick.spec is not None else None
    if pick.spec is not None and pick.file:
        run.answers["entry-default"] = pick.file
    edition = run.edition
    if edition.enterprise:
        console.print(f"  [green]Enterprise[/] [dim]{', '.join(sorted(edition.features))}[/]")

    # 3. What ---------------------------------------------------------------------
    _step(3, "What to include")
    choices = _choices(run)
    available = {c.key for c in choices if not c.disabled}
    if include is not None:
        defaults = wanted
    elif saved.get("components"):
        defaults = set(saved["components"])
    else:
        defaults = {c.key for c in CATALOGUE if c.key in available and c.recommended(run)}
    defaults = (defaults - unwanted) & available
    if wanted - available:
        for key in sorted(wanted - available):
            console.print(f"  [yellow]{key}[/] unavailable: {BY_KEY[key].unavailable(run)}")
    picked = prompter.multiselect(
        "What should AgentFox cover?", choices, [c.key for c in CATALOGUE if c.key in defaults]
    )
    run.picked = picked

    # 4. How strict ---------------------------------------------------------------
    run.mode = mode or prompter.select("How strict to start?", MODES, saved.get("mode", "observe"))

    # 5. Follow-ups ---------------------------------------------------------------
    for key in picked:
        component = BY_KEY[key]
        if component.ask is not None:
            component.ask(run)
        # The agent follows the file auto() goes into: the one that file starts. Before
        # the next question, so the tools offered are that agent's.
        entry = run.answers.get("python-app")
        if key == "python-app" and entry and entry != "none" and entry != pick.file:
            pick = _follow_file(ctx, pick, entry, agent, run)
    if pick.others and pick.spec is not None:
        # The best other first runs, by the key `--agent` takes.
        shown = pick.others[:3]
        how = "pick its file above, or run" if interactive else "run"
        console.print(
            f"  [yellow]{pick.systems} separate agent systems here[/] — setting up "
            f"[bold]{escape(run.agent)}[/] only"
            + (f" [dim]({escape(pick.file)})[/]" if pick.file else "")
            + f". For another, {how} [cyan]agentfox up --agent <name>[/]: "
            + ", ".join(f"[cyan]{escape(k)}[/]" for k in shown)
            + (
                f" [dim](+{len(pick.others) - len(shown)} more: `agentfox scan`)[/]"
                if len(pick.others) > len(shown)
                else ""
            )
        )
    # The name, shown and changeable: what auto("…") is called with and what the
    # dashboard lists. `--agent` decides it without asking.
    if any(key in picked for key in _NAMED) and agent is None:
        run.agent = slugify(prompter.text("Agent name", run.agent))

    # 6. Plan ---------------------------------------------------------------------
    _step(4, "Plan")
    console.print(f"  [bold]{chosen.key}[/] · {escape(_short(chosen.backend.where))}")
    if any(key in picked for key in _NAMED):
        tools = run.system_tools
        console.print(
            f"  [cyan]•[/] agent [bold]{escape(run.agent)}[/]"
            + (f" [dim]· {plural(len(tools), 'tool')} of its own[/]" if tools else "")
        )
    for key in picked:
        console.print(f"  [cyan]•[/] {BY_KEY[key].label}")
    console.print(
        f"  [cyan]•[/] policies: {next(m.label for m in MODES if m.key == run.mode).lower()}"
    )
    if dry_run:
        console.print("\n  [dim]--dry-run: nothing changed.[/]")
        return
    if interactive and not prompter.confirm("Set this up?", default=True):
        console.print("  [dim]Nothing changed.[/]")
        raise typer.Exit(0)

    # 7. Do it --------------------------------------------------------------------
    _step(5, "Setting up")
    for component in CATALOGUE:
        if component.key not in picked:
            continue
        try:
            component.apply(run)
        except Exception as exc:  # one component failing must not stop the rest
            run.failed(component.key, f"{component.label}: {exc}")
    apply_mode(run)

    env_path = write_env(root, {**chosen.env, **run.env}) if (chosen.env or run.env) else None
    save_answers(
        root,
        {
            "target": chosen.key,
            "api_url": chosen.api_url if chosen.remote else None,
            "dashboard_url": chosen.dashboard_url or None,
            "components": picked,
            "mode": run.mode,
            "agent": run.agent,
            "harnesses": run.answers.get("coding-agents"),
            "entry_point": run.answers.get("python-app"),
            "environment": saved.get("environment", "development"),
            "email": email or saved.get("email"),
            "scans": run.answers.get("scans", saved.get("scans")),
        },
    )

    # 8. Summary ------------------------------------------------------------------
    failed = [o for o in run.outcomes if o.status == "failed"]
    lines = [
        f"[bold]{'Done' if not failed else 'Done, with problems'}[/] — "
        f"{sum(o.status == 'done' for o in run.outcomes)} set up"
        + (f", [red]{len(failed)} failed[/]" if failed else ""),
    ]
    if run.running:
        lines.append("\n[bold]Running in the background[/]")
        lines.extend(f"  {escape(item)}" for item in run.running)
    if env_path is not None:
        lines.append(
            f"\n[bold]Environment[/] {STATE_DIR}/{ENV_FILE} [dim](0600, git-ignored)[/]\n"
            f"  set -a; . {STATE_DIR}/{ENV_FILE}; set +a"
        )
    lines.extend(f"\n{escape(note)}" for note in chosen.notes)
    steps = (
        _first_steps(run)
        + run.next_steps
        + run.later_steps
        + [
            ("agentfox doctor", "is everything configured the way you think?"),
            ("agentfox up", f"again any time — answers are in {STATE_DIR}/{ANSWERS_FILE}"),
        ]
    )
    lines.append("\n[bold]Next[/]")
    width = min(max(len(cmd) for cmd, _ in steps), 44)
    lines.extend(f"  [cyan]{escape(cmd):<{width}}[/]  [dim]{escape(why)}[/]" for cmd, why in steps)
    hidden = [c.label.split(" — ")[0].lower() for c in CATALOGUE if _hidden(c, run)]
    if hidden:
        # Said once, here, rather than as greyed-out options in the first run's list.
        lines.append(
            f"\n[dim]Also available with AgentFox Enterprise (in Cloud, or self-hosted): "
            f"{', '.join(hidden)}.[/]"
        )
    console.print()
    console.print(Panel("\n".join(lines), border_style="red" if failed else "green"))
    if failed:
        raise typer.Exit(1)


def _first_steps(run: Run) -> list[tuple[str, str]]:
    """What to do the moment setup ends: run the app that now records, look at what
    it saw, then attack-test it. Review and tightening come after."""
    steps: list[tuple[str, str]] = []
    governed = "python-app" in run.picked or "gateway" in run.picked
    entry = run.answers.get("python-file")
    if "python-app" in run.picked and entry and entry != "none":
        from agentfox.apps.cli.wizard.detect import _MAIN_GUARD

        try:
            script = bool(_MAIN_GUARD.search((run.ctx.root / entry).read_text(errors="ignore")))
        except OSError:
            script = False
        # `python <file>` only for a file that runs as a script; a graph module or a
        # package entry point is started the way it always was.
        steps.append(
            (
                f"python {entry}" if script else "run your app",
                f'as usual: {entry} now calls auto("{run.agent}"), which records every call',
            )
        )
    elif "python-app" in run.picked:
        steps.append(("run your app", f'after adding the auto("{run.agent}") line shown above'))
    elif "gateway" in run.picked:
        steps.append(
            ("run your app", f"with {STATE_DIR}/{ENV_FILE} loaded: its model calls go through")
        )
    if governed or "coding-agents" in run.picked:
        steps.append(("agentfox findings", "what it saw and what it would have stopped"))
    if governed:
        steps.append(
            (
                f"agentfox test redteam {run.agent}",
                "attack-test it: prompt injection, exfiltration, destructive actions",
            )
        )
    return steps


def register(app: typer.Typer) -> None:
    app.command(name="up")(up)
