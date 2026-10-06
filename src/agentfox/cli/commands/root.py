"""Top-level verbs: `version`, `seed`, `demo`, `serve` and `analyse-action`."""

from __future__ import annotations

import typer
from rich.panel import Panel

from agentfox import __version__
from agentfox.cli._style import SEVERITY_COLOUR
from agentfox.cli.commands._shared import _session, console


def version() -> None:
    """Show the version of everything that takes part in a decision."""
    from agentfox.capabilities.compliance.catalog import load_catalog
    from agentfox.core.config import get_settings

    settings = get_settings()
    catalog = load_catalog()
    console.print(
        Panel.fit(
            f"[bold]AgentFox[/] {__version__}\n"
            f"control catalog   {catalog.get('version')} "
            f"([yellow]{catalog.get('review_status')}[/])\n"
            f"policy engine     {settings.policy_engine}\n"
            f"default provider  {settings.default_provider}\n"
            f"default mode      {settings.default_policy_mode}\n"
            f"fail mode         {settings.fail_mode}\n"
            f"latency budget    {settings.enforcement_budget_ms}ms\n"
            f"egress allowed    {settings.allow_egress}",
            border_style="cyan",
        )
    )


def _mask_key(key: str) -> str:
    """Keep the recognisable prefix (``nom_agt_``) and four characters, hide the rest."""
    import re

    match = re.match(r"^((?:[a-z]+_)+)", key)
    prefix = match.group(1) if match else ""
    return f"{prefix}{key[len(prefix) : len(prefix) + 4]}…"


def seed(
    show_keys: bool = typer.Option(
        False,
        "--show-keys",
        help="Print newly issued agent API keys in full. Keys are shown only once, "
        "when first issued; this flag is the only way to see them.",
    ),
) -> None:
    """Load a demonstrable environment: three agents, policies, controls and an
    eval suite. It records no traffic; `agentfox demo` sends sample requests through
    the seeded agents, which is what fills traces, decisions and findings."""
    from agentfox.fixtures.seed import seed as run_seed

    with _session() as session:
        summary = run_seed(session)
    console.print("[green]seeded[/]")
    catalog = summary["catalog"]
    # "0 created" is the normal result of a second run, and read as a failure every
    # time. Say how many controls are *there*, and mention creation only when the run
    # actually created some.
    created = catalog["controls_created"]
    console.print(
        f"  controls    {catalog['mappings']} framework mappings "
        f"([yellow]{catalog['review_status']}[/])"
        + (f", {created} control(s) newly created" if created else ", all already present")
    )
    console.print(f"  obligations {summary['obligations']}")
    console.print(f"  policies    {', '.join(summary.get('policies', []))}")
    console.print(f"  agents      {', '.join(summary['agents'])}")
    console.print(f"  eval suite  {summary['eval_suite']}")
    credentials = summary.get("credentials") or {}
    for slug, key in credentials.items():
        console.print(f"  [dim]key {slug}: {key if show_keys else _mask_key(key)}[/]")
    if credentials and not show_keys:
        console.print(
            "  [dim]keys masked. Only a hash is stored and each key is issued once — "
            "`agentfox admin seed --show-keys` on a fresh database is the only way to see "
            "them in full.[/]"
        )

    from agentfox.cli.onboarding import _print_next_steps

    _print_next_steps(
        [
            (
                "agentfox demo",
                "send sample requests through the seeded agents: traces, decisions, findings",
            ),
            ("agentfox permit list", "what each seeded agent is allowed to do"),
            ("agentfox doctor", "check the runtime configuration"),
        ]
    )


def demo() -> None:
    """Run the end-to-end walkthrough (offline)."""
    from agentfox.core.db import init_db, session_scope
    from agentfox.core.models import Agent
    from agentfox.fixtures.seed import register_scripts
    from agentfox.fixtures.seed import seed as run_seed

    init_db()
    with session_scope() as session:
        if session.query(Agent).count() == 0:
            console.print("[dim]no agents found — seeding first[/]")
            run_seed(session)
    # The offline provider's scripted replies live in process memory, so a demo run
    # against an already-seeded database has to re-register them.
    register_scripts()

    from agentfox.cli.demo import run

    run()


def serve(
    host: str = "127.0.0.1",
    port: int = 8080,
    reload: bool = False,
) -> None:
    """Start the gateway and control-plane API."""
    import uvicorn

    console.print(f"[cyan]AgentFox[/] {__version__} → http://{host}:{port}")
    console.print(f"  [dim]inline:  POST http://{host}:{port}/v1/chat/completions[/]")
    console.print(f"  [dim]api:     http://{host}:{port}/api/agents[/]")
    console.print(f"  [dim]docs:    http://{host}:{port}/docs[/]")
    from agentfox.gateway.auth import auth_posture

    posture = auth_posture()
    if posture.startswith("DEVELOPMENT"):
        console.print(f"  [yellow]auth:    {posture}[/]")
    else:
        console.print(f"  [dim]auth:    {posture}[/]")
    uvicorn.run("agentfox.gateway.app:app", host=host, port=port, reload=reload)


def analyse_action(
    statement: str = typer.Argument(..., help="SQL, shell command or URL to analyse"),
    kind: str = typer.Option("sql", help="sql | shell | http"),
    method: str = typer.Option("GET", help="HTTP method, when kind=http"),
    dialect: str = typer.Option("postgres", help="SQL dialect"),
    environment: str = typer.Option("production", help="environment the action binds to"),
) -> None:
    """Read an artefact and say what running it would actually do.

    Deterministic, offline and immediate: no database, no model, no network. The point
    is that an engineer can check a generated statement before it is ever executed.
    """
    from agentfox.capabilities.detection.actions import (
        analyse_http,
        analyse_shell,
        analyse_sql,
        summarise,
    )

    if kind == "shell":
        analysis = analyse_shell(statement)
    elif kind == "http":
        analysis = analyse_http(method, statement)
    else:
        analysis = analyse_sql(statement, dialect=dialect)

    from rich.markup import escape

    summary = summarise([analysis], environment)
    colour = SEVERITY_COLOUR.get(analysis.severity, "green")
    # A statement that was never analysed (no sqlglot, or it did not parse) has no
    # known reversibility; printing "reversible" for it would be a guess in the
    # safe-looking direction.
    if kind == "sql" and not analysis.parsed:
        reversibility = "reversibility unknown (not analysed)"
    else:
        reversibility = "reversible" if analysis.reversible else "IRREVERSIBLE"
    targets = ", ".join(analysis.targets) or "—"
    console.print(
        f"[bold]{escape(analysis.operation)}[/] · blast radius "
        f"[{colour}]{escape(analysis.blast_radius)}[/] · {reversibility} · "
        f"{len(analysis.targets)} target(s): {escape(targets)}"
    )
    if not summary.get("risks"):
        console.print("  [green]no risks identified[/]")
    for risk in summary.get("risks", []):
        risk_colour = SEVERITY_COLOUR.get(risk["severity"], "dim")
        # Escaped: risk text quotes statements and install hints ("agentfox[sql]")
        # that Rich would otherwise read as markup and silently drop.
        console.print(
            f"  [{risk_colour}]{risk['severity']}[/] {escape(risk['code'])} — "
            f"{escape(str(risk['detail']))}"
        )
    if summary.get("critical"):
        raise typer.Exit(1)


def register(app: typer.Typer) -> None:
    """Register the top-level verbs on the root app, in their `--help` order."""
    app.command()(version)
    app.command()(seed)
    app.command()(demo)
    app.command()(serve)
    app.command()(analyse_action)
