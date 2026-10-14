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
from pathlib import Path

import typer
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel

from agentfox.apps.cli.wizard.components import BY_KEY, CATALOGUE, MODES, Run, apply_mode
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
    harnesses = [h.display for h in ctx.harnesses if h.present]
    rows.append(("coding agents", ", ".join(harnesses) or "none found"))
    flagged = [s for s in ctx.skills if s["issues"]]
    if ctx.skills:
        named = ", ".join(s["skill"] for s in flagged[:3])
        issues = f" [red]({len(flagged)} with issues: {named})[/]" if flagged else ""
        rows.append(("skills", f"{len(ctx.skills)}{issues}"))
    machine = ctx.machine
    if machine is not None and machine.configs:
        issues = sum(len(e["issues"]) for e in machine.servers) + machine.skill_issues
        clients = sorted({c["client"] for c in machine.configs})
        rows.append(
            (
                "this machine",
                f"{len(machine.servers)} MCP servers across {', '.join(clients)}"
                + (f", [yellow]{issues} issues[/]" if issues else "")
                + (
                    f", [red]{len(machine.trifectas)} lethal trifecta(s)[/]"
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


def _choices(run: Run) -> list[Choice]:
    out = []
    for component in CATALOGUE:
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
        None, "--agent", help="Name for your agent. Default: the project's."
    ),
    api_url: str | None = typer.Option(
        None,
        "--api-url",
        envvar="AGENTFOX_API_URL",
        help="Gateway address, for self-hosted or cloud.",
    ),
    api_token: str | None = typer.Option(
        None, "--api-token", envvar="AGENTFOX_API_TOKEN", help="API key, for self-hosted or cloud."
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

    run = Run(
        ctx=ctx,
        target=chosen,
        prompter=prompter,
        console=console,
        agent=agent or saved.get("agent") or ctx.project,
        start=start,
        interactive=interactive,
    )
    edition = run.edition
    if edition.enterprise:
        console.print(f"  [green]Enterprise[/] [dim]{', '.join(sorted(edition.features))}[/]")
    else:
        console.print(
            "  [dim]Open core. Compliance, evidence and monitoring are AgentFox Enterprise: "
            "included in Cloud, free self-hosted for one workspace and four agents.[/]"
        )

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

    # 4. How strict ---------------------------------------------------------------
    run.mode = mode or prompter.select("How strict to start?", MODES, saved.get("mode", "observe"))

    # 5. Follow-ups ---------------------------------------------------------------
    if any(key in picked for key in _NAMED) and agent is None:
        run.agent = slugify(prompter.text("Name for your agent", run.agent))
    for key in picked:
        component = BY_KEY[key]
        if component.ask is not None:
            component.ask(run)

    # 6. Plan ---------------------------------------------------------------------
    _step(4, "Plan")
    console.print(f"  [bold]{chosen.key}[/] · {escape(chosen.backend.where)}")
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
    steps = run.next_steps + [
        ("agentfox doctor", "is everything configured the way you think?"),
        ("agentfox up", f"again any time — answers are in {STATE_DIR}/{ANSWERS_FILE}"),
    ]
    lines.append("\n[bold]Next[/]")
    width = max(len(cmd) for cmd, _ in steps)
    lines.extend(f"  [cyan]{escape(cmd):<{width}}[/]  [dim]{escape(why)}[/]" for cmd, why in steps)
    console.print()
    console.print(Panel("\n".join(lines), border_style="red" if failed else "green"))
    if failed:
        raise typer.Exit(1)


def register(app: typer.Typer) -> None:
    app.command(name="up")(up)
