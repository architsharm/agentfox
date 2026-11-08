"""Top-level verbs: `version`, `seed`, `demo`, `serve`, `serve-models` and `analyse-action`."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.panel import Panel

from agentfox import __version__
from agentfox.apps.cli._style import SEVERITY_COLOUR
from agentfox.apps.cli.commands._shared import _session, console


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

    from agentfox.apps.cli.onboarding import _print_next_steps

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


def demo(
    in_workspace: bool = typer.Option(
        False,
        "--in-workspace",
        help="Write the demo's agents, traffic and findings into your workspace database "
        "instead of its own. They stay there.",
    ),
) -> None:
    """Run the end-to-end walkthrough (offline), in a database of its own.

    Three made-up agents, sample traffic and the findings it opens go to `demo.db`
    beside your workspace database, so `agentfox findings` in a real project never
    opens with the demo's. The closing panel says how to look around it."""
    from contextlib import nullcontext

    from agentfox.apps.cli.demo import footer, own_database, run
    from agentfox.core.config import get_settings

    workspace = get_settings().database_url
    scope = nullcontext((None, workspace)) if in_workspace else own_database()
    with scope as (demo_url, workspace_url):
        _prepare_demo()
        summary = run()
    console.print()
    console.rule(style="green")
    console.print(
        footer(demo_url, workspace_url, evidence=bool(summary.get("evidence_available"))),
        soft_wrap=True,
    )


def _prepare_demo() -> None:
    from agentfox.core.db import init_db, session_scope
    from agentfox.core.models import Agent
    from agentfox.fixtures.seed import register_scripts
    from agentfox.fixtures.seed import seed as run_seed

    init_db()
    with session_scope() as session:
        if session.query(Agent).count() == 0:
            console.print("[dim]setting up the demo's agents (first run)[/]")
            run_seed(session)
    # The offline provider's scripted replies live in process memory, so a demo run
    # against an already-seeded database has to re-register them.
    register_scripts()


def _serve_record() -> Path:
    from agentfox.core.config import run_dir

    return run_dir() / "serve.json"


def running_serve() -> dict | None:
    """The `agentfox serve` this installation started and that is still alive, as
    ``{"pid", "port", "database"}``; None when there is none (or it died without
    cleaning up, in which case its record is removed)."""
    import json
    import os

    path = _serve_record()
    try:
        record = json.loads(path.read_text())
        os.kill(int(record["pid"]), 0)
    except (OSError, ValueError, KeyError, TypeError):
        path.unlink(missing_ok=True)
        return None
    return record


def _record_serve(port: int) -> None:
    """Say which database this API serves, so a second project's `agentfox up` can
    tell "the API on :8080 is this installation's, on this database" from "something
    else is on the port". Removed again on exit."""
    import atexit
    import json
    import os

    from agentfox.core.config import get_settings

    path = _serve_record()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"pid": os.getpid(), "port": port, "database": get_settings().database_url})
        )
    except OSError:
        return
    pid = os.getpid()

    def _remove() -> None:
        try:
            if json.loads(path.read_text()).get("pid") == pid:
                path.unlink()
        except (OSError, ValueError):
            pass

    atexit.register(_remove)


def serve(
    host: str = "127.0.0.1",
    port: int = 8080,
    reload: bool = False,
) -> None:
    """Start the gateway and control-plane API.

    It serves JSON: the API under /api, the gateway under /v1, and interactive API
    docs at /docs. The web dashboard is AgentFox Cloud (`agentfox up --target cloud`)
    or the self-hosted stack (`agentfox up --target self-hosted`)."""
    import uvicorn

    _record_serve(port)
    console.print(f"[cyan]AgentFox[/] {__version__} → http://{host}:{port}")
    console.print(f"  [dim]inline:  POST http://{host}:{port}/v1/chat/completions[/]")
    console.print(f"  [dim]api:     http://{host}:{port}/api/agents[/]")
    console.print(f"  [dim]docs:    http://{host}:{port}/docs[/]")
    console.print(
        "  [dim]web dashboard: not served here — sign in to AgentFox Cloud "
        "(`agentfox up --target cloud`) or self-host it (`agentfox up --target self-hosted`)[/]"
    )
    from agentfox.platform.identity.operators import auth_posture

    posture = auth_posture()
    if posture.startswith("DEVELOPMENT"):
        console.print(f"  [yellow]auth:    {posture}[/]")
    else:
        console.print(f"  [dim]auth:    {posture}[/]")
    uvicorn.run("agentfox.apps.gateway.app:app", host=host, port=port, reload=reload)


def serve_models(
    host: str = "127.0.0.1",
    port: int = 8090,
    workers: int = typer.Option(1, help="Processes; each loads every model once."),
) -> None:
    """Run the model server: model-backed detectors for gateways that should not
    hold weights. Point a gateway at it with AGENTFOX_MODEL_SERVER_URL."""
    import uvicorn

    from agentfox.capabilities.detection.loading import model_device
    from agentfox.core.config import get_settings

    settings = get_settings()
    loopback = host in {"127.0.0.1", "localhost", "::1"}
    if not loopback and not settings.model_server_token:
        # Anyone who can reach the port could otherwise run our models on our GPU
        # and read nothing less than the content we screen.
        console.print(
            "[red]refusing to listen on a non-loopback address without "
            "AGENTFOX_MODEL_SERVER_TOKEN[/]"
        )
        raise typer.Exit(2)
    if settings.model_server_url:
        console.print(
            "[yellow]AGENTFOX_MODEL_SERVER_URL is ignored here: this is the model server[/]"
        )
    console.print(f"[cyan]AgentFox model server[/] {__version__} → http://{host}:{port}")
    console.print(f"  [dim]device:  {model_device()}[/]")
    console.print(f"  [dim]health:  GET http://{host}:{port}/health[/]")
    console.print(
        f"  [dim]auth:    {'bearer token' if settings.model_server_token else 'none (loopback)'}[/]"
    )
    uvicorn.run("agentfox.apps.model_server:app", host=host, port=port, workers=workers)


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
    app.command(name="serve-models")(serve_models)
    app.command()(analyse_action)
