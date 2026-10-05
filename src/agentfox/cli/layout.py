"""The visible shape of the CLI: thirteen verbs in six panels.

The commands themselves live where they always did (``main.py``, ``onboarding.py``,
``controls_cli.py`` …). This module only decides what ``agentfox --help`` shows and
under which name. It runs once, after every other module has registered its
commands, and does three things:

1. registers the existing callbacks a second time under the new tree
   (Start · See · Watch · Contain · Prove · Operate);
2. marks every old group and command ``hidden`` — it still parses and runs, it just
   no longer crowds the help screen;
3. swaps the root group for one that adds ``--version``, orders the panels, and prints
   a one-line "now called …" hint on stderr when someone types an old name.

Nothing here rewrites a command body, so a change to what a command *does* never
conflicts with a change to where it *lives*. Commands are looked up by their CLI name
(``compliance risk``), not by Python symbol, for the same reason.

Old paths are a compatibility promise, not a courtesy: ``hooks run``, ``hooks
daemon`` and ``mcp serve`` are written into users' agent configs as stdio endpoints,
and scripts in the wild call ``agentfox check --fail``. ``tests/test_cli_layout.py``
holds the full pre-consolidation command list and fails if any of it stops resolving.
"""

from __future__ import annotations

import copy
import sys
from typing import Any

import click
import typer
from typer.core import TyperGroup
from typer.main import get_command_name
from typer.models import CommandInfo, TyperInfo

START, SEE, WATCH, CONTAIN, PROVE, OPERATE = (
    "Start",
    "See",
    "Watch",
    "Contain",
    "Prove",
    "Operate",
)

# The visible top level, in the order `--help` lists it. Keep this at thirteen or
# fewer: tests/test_cli_layout.py enforces the ceiling.
VISIBLE: list[tuple[str, str]] = [
    ("init", START),
    ("demo", START),
    ("scan", SEE),
    ("agents", SEE),
    ("serve", WATCH),
    ("findings", WATCH),
    ("permit", CONTAIN),
    ("declare", CONTAIN),
    ("policy", CONTAIN),
    ("test", PROVE),
    ("report", PROVE),
    ("doctor", OPERATE),
    ("admin", OPERATE),
]

# Old top-level name -> where it lives now. Printed (stderr, terminals only) when the
# old name is used. Names absent from this map are hidden silently.
RENAMED: dict[str, str] = {
    "check": "agentfox scan",
    "quickscan": "agentfox scan --sessions",
    "quickstart": "agentfox init",
    "version": "agentfox --version (or `agentfox admin version`)",
    "seed": "agentfox admin seed",
    "analyse-action": "agentfox test action",
    "eval": "agentfox test (drift: `agentfox report drift`)",
    "audit": "agentfox report verify / agentfox admin checkpoint",
    "evidence": "agentfox report evidence",
    "compliance": "agentfox report (catalog upkeep: `agentfox admin catalog`)",
    "redteam": "agentfox test redteam / agentfox test probes",
    "tools": "agentfox declare tool / declare triggers / declare list",
    "access": "agentfox declare scope / declare reference",
    "db": "agentfox admin db",
    "auth": "agentfox admin auth",
    "boundary": "agentfox declare boundary / agentfox test boundary",
    "sources": "agentfox declare source / declare list sources",
    "escalation": "agentfox declare escalation / agentfox report escalations",
    "entitlement": "agentfox permit user / declare principal / report entitlement",
    "guardrails": "agentfox policy rules",
    "capability": "agentfox permit",
    "proposals": "agentfox policy proposals",
}

# Protocol endpoints written into users' configs (`hooks run`, `hooks daemon`,
# `mcp serve`). They are hidden but must stay byte-for-byte quiet: no hint, ever.
SILENT = {"hooks", "mcp"}


# ---------------------------------------------------------------------------
# Click group classes
# ---------------------------------------------------------------------------


def default_group(default: str, routes: dict[str, str] | None = None) -> type[TyperGroup]:
    """A group that runs ``default`` when the first word is not one of its subcommands.

    ``agentfox scan``, ``agentfox scan ./repo --fail`` and ``agentfox scan mcp …`` all
    work: anything that is not a known subcommand (or ``--help``) is handed to the
    default. ``routes`` maps a flag to a different subcommand, so ``scan --sessions``
    can reach the session scan without merging two commands' option sets.
    """
    route_map = dict(routes or {})

    class DefaultGroup(TyperGroup):
        default_command = default
        flag_routes = route_map

        def parse_args(self, ctx: click.Context, args: list[str]) -> list[str]:
            args = list(args)
            first = args[0] if args else None
            if first is None or (first not in self.commands and first not in ctx.help_option_names):
                target = self.default_command
                for flag, sub in self.flag_routes.items():
                    if flag in args:
                        args.remove(flag)
                        target = sub
                        break
                args.insert(0, target)
            return super().parse_args(ctx, args)

    return DefaultGroup


def _print_version(ctx: click.Context, _param: click.Parameter, value: bool) -> None:
    if not value or ctx.resilient_parsing:
        return
    from .. import __version__

    click.echo(f"agentfox {__version__}")
    ctx.exit()


def _stderr_is_tty() -> bool:
    try:
        return sys.stderr.isatty()
    except (AttributeError, ValueError):
        return False


class RootGroup(TyperGroup):
    """The `agentfox` group: panel order, `--version`, and rename hints."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.params.insert(
            0,
            click.Option(
                ["--version"],
                is_flag=True,
                expose_value=False,
                is_eager=True,
                callback=_print_version,
                help="Print the version and exit.",
            ),
        )

    def list_commands(self, ctx: click.Context) -> list[str]:
        order = {name: i for i, (name, _) in enumerate(VISIBLE)}
        names = super().list_commands(ctx)
        return sorted(names, key=lambda n: order.get(n, len(order)))

    def resolve_command(self, ctx: click.Context, args: list[str]):
        name, cmd, rest = super().resolve_command(ctx, args)
        # Only a person at a terminal sees the hint. Scripts, CI and the MCP server's
        # subprocesses get exactly the output they got before.
        if name in RENAMED and name not in SILENT and not ctx.resilient_parsing:
            if _stderr_is_tty():
                click.echo(
                    f"note: `agentfox {name}` is now `{RENAMED[name]}` (the old name still works)",
                    err=True,
                )
        return name, cmd, rest


# ---------------------------------------------------------------------------
# Lookup helpers — by CLI name, never by Python symbol
# ---------------------------------------------------------------------------


def _command_name(info: CommandInfo) -> str:
    return info.name or get_command_name(info.callback.__name__)


def _group(parent: typer.Typer, name: str) -> TyperInfo:
    for info in parent.registered_groups:
        if info.name == name:
            return info
    raise LookupError(f"no `{name}` group registered")


def _command(parent: typer.Typer, name: str) -> CommandInfo:
    for info in parent.registered_commands:
        if _command_name(info) == name:
            return info
    raise LookupError(f"no `{name}` command registered")


def _find(app: typer.Typer, *path: str) -> CommandInfo:
    parent = app
    for word in path[:-1]:
        parent = _group(parent, word).typer_instance
    return _command(parent, path[-1])


def _alias(target: typer.Typer, info: CommandInfo, name: str, *, hidden: bool = False) -> None:
    clone = copy.copy(info)
    clone.name = name
    clone.hidden = hidden
    clone.rich_help_panel = None
    target.registered_commands.append(clone)


def _hide_group(info: TyperInfo) -> None:
    info.hidden = True
    info.rich_help_panel = None


def _new_group(help: str, cls: type[TyperGroup] | None = None, **kwargs: Any) -> typer.Typer:
    if cls is not None:
        kwargs["cls"] = cls
    kwargs.setdefault("no_args_is_help", cls is None)
    return typer.Typer(help=help, **kwargs)


# ---------------------------------------------------------------------------
# The tree
# ---------------------------------------------------------------------------


def apply_layout(app: typer.Typer) -> None:
    """Build the visible tree on top of the registered commands. Idempotent."""
    if getattr(app, "_agentfox_layout_applied", False):
        return
    app._agentfox_layout_applied = True  # type: ignore[attr-defined]

    find = lambda *path: _find(app, *path)  # noqa: E731
    panels: dict[str, str] = dict(VISIBLE)
    sub = {info.name: info for info in app.registered_groups}

    # Every pre-existing top-level entry is hidden first; the visible ones are then
    # switched back on (or replaced) below.
    for info in app.registered_commands:
        info.hidden = _command_name(info) not in panels
    for info in app.registered_groups:
        if info.name not in panels:
            _hide_group(info)

    # -- See: scan ---------------------------------------------------------------
    # `scan` already existed as a group (`scan mcp`, `scan skills`). It becomes a
    # default-command group: bare `scan [PATH]` is the repo scan `check` was.
    scan = sub["scan"]
    scan.cls = default_group("repo", routes={"--sessions": "sessions"})
    scan.no_args_is_help = False
    scan.help = (
        "Find what is worth governing: a repo, local sessions, an MCP server, the runtime.\n\n"
        "`agentfox scan [PATH] [--fail] [--json]` scans a repository (the default). "
        "`agentfox scan --sessions [PATH]` also reads local AI-tool sessions and runs "
        "the live detector check. `mcp`, `skills` and `runtime` scan the rest."
    )
    scan_app = scan.typer_instance
    _alias(scan_app, find("check"), "repo")
    _alias(scan_app, find("quickscan"), "sessions", hidden=True)
    _alias(scan_app, find("agents", "discover"), "runtime")

    # -- See: agents -------------------------------------------------------------
    find("agents", "discover").hidden = True  # -> scan runtime
    find("agents", "controls").hidden = True  # -> agents list --stopped

    # -- Watch: serve --------------------------------------------------------------
    serve_info = find("serve")
    app.registered_commands.remove(serve_info)
    serve_app = _new_group(
        "Run the gateway and control-plane API, or the MCP server for AI clients.\n\n"
        "`agentfox serve [--host] [--port] [--reload]` starts the API (the default); "
        "`agentfox serve mcp` speaks MCP over stdio.",
        cls=default_group("api"),
    )
    _alias(serve_app, serve_info, "api")
    _alias(serve_app, find("mcp", "serve"), "mcp")
    app.add_typer(serve_app, name="serve")

    # -- Contain: permit -----------------------------------------------------------
    permit_app = _new_group("Grant, list and withdraw what an agent — or an end user — may do.")
    _alias(permit_app, find("capability", "grant"), "grant")
    _alias(permit_app, find("capability", "list"), "list")
    _alias(permit_app, find("capability", "revoke"), "revoke")
    _alias(permit_app, find("entitlement", "grant"), "user")
    app.add_typer(permit_app, name="permit")

    # -- Contain: declare ----------------------------------------------------------
    declare_app = _new_group(
        "Declare the facts containment reasons over: tools, data scope, sources, hand-offs.\n\n"
        "What a tool can do, which column says whose row it is, what an agent has no "
        "data for, which sources are authoritative, and when to hand off to a person."
    )
    _alias(declare_app, find("tools", "declare"), "tool")
    _alias(declare_app, find("tools", "set-triggers"), "triggers")
    _alias(declare_app, find("access", "declare-scope"), "scope")
    _alias(declare_app, find("access", "declare-reference"), "reference")
    _alias(declare_app, find("boundary", "set"), "boundary")
    _alias(declare_app, find("sources", "add"), "source")
    _alias(declare_app, find("sources", "import"), "import-sources")
    _alias(declare_app, find("escalation", "set"), "escalation")
    _alias(declare_app, find("entitlement", "principal"), "principal")
    declare_app.command("list")(_declared_list(find("tools", "list"), find("sources", "list")))
    app.add_typer(declare_app, name="declare")

    # -- Contain: policy -----------------------------------------------------------
    policy_app = sub["policy"].typer_instance
    rules = sub["guardrails"]
    _alias(policy_app, find("guardrails", "catalogue"), "catalogue")
    _alias(policy_app, find("guardrails", "compile"), "compile")
    policy_app.add_typer(
        rules.typer_instance,
        name="rules",
        help="Business rules in plain terms: apply, show, check, explain, suggest, graph.",
    )
    policy_app.add_typer(sub["proposals"].typer_instance, name="proposals")

    # -- Prove: test ---------------------------------------------------------------
    test_app = _new_group(
        "Prove the controls hold before you ship: score, gate, attack, and dry-run."
    )
    for name in ("run", "gate", "baseline", "suites", "online"):
        _alias(test_app, find("eval", name), name)
    _alias(test_app, find("redteam", "run"), "redteam")
    _alias(test_app, find("redteam", "probes"), "probes")
    _alias(test_app, find("analyse-action"), "action")
    _alias(test_app, find("boundary", "check"), "boundary")
    _alias(test_app, find("guardrails", "test"), "rule")
    app.add_typer(test_app, name="test")

    # -- Prove: report -------------------------------------------------------------
    # SEAM: a top-level `report` command (the one-page summary, landing from another
    # branch in its own module) is absorbed here automatically: it becomes
    # `report summary` and the group's default. Until it lands, bare `report` is
    # compliance posture (`report status`).
    summary_info = None
    for info in list(app.registered_commands):
        if _command_name(info) == "report":
            summary_info = info
            app.registered_commands.remove(info)
    report_app = _new_group(
        "What you can show an auditor: posture, evidence, risk, sign-off.\n\n"
        "Bare `agentfox report` prints the summary; the subcommands go deeper.",
        cls=default_group("summary" if summary_info else "status"),
    )
    if summary_info is not None:
        _alias(report_app, summary_info, "summary")
    _alias(report_app, find("compliance", "status"), "status")
    _alias(report_app, find("evidence", "export"), "evidence")
    _alias(report_app, find("audit", "verify"), "verify")
    for name in ("risk", "obligations", "frameworks", "board", "review-packet"):
        _alias(report_app, find("compliance", name), name)
    _alias(report_app, find("compliance", "review"), "signoff")
    _alias(report_app, find("entitlement", "report"), "entitlement")
    _alias(report_app, find("escalation", "scan"), "escalations")
    _alias(report_app, find("eval", "drift"), "drift")
    app.add_typer(report_app, name="report")

    # -- Operate: admin ------------------------------------------------------------
    admin_app = _new_group("Run the deployment: tokens, schema, catalog upkeep, hooks, seed data.")
    admin_app.add_typer(sub["auth"].typer_instance, name="auth")
    admin_app.add_typer(sub["db"].typer_instance, name="db")
    catalog_app = _new_group("Keep the control catalog and its computed status current.")
    for name in ("sync", "compute", "validate"):
        _alias(catalog_app, find("compliance", name), name)
    admin_app.add_typer(catalog_app, name="catalog")
    _alias(admin_app, find("audit", "checkpoint"), "checkpoint")
    _alias(admin_app, find("seed"), "seed")
    _alias(admin_app, find("version"), "version")
    admin_app.add_typer(sub["hooks"].typer_instance, name="hooks")
    mcp_admin = _new_group("Inspect the MCP server. To run it: `agentfox serve mcp`.")
    _alias(mcp_admin, find("mcp", "tools"), "tools")
    admin_app.add_typer(mcp_admin, name="mcp")
    app.add_typer(admin_app, name="admin")

    # -- panels and root -------------------------------------------------------------
    for info in app.registered_commands:
        name = _command_name(info)
        if name in panels:
            info.hidden = False
            info.rich_help_panel = panels[name]
    for info in app.registered_groups:
        if info.name in panels:
            info.hidden = False
            info.rich_help_panel = panels[info.name]
    app.info.cls = RootGroup


def _declared_list(tools_list: CommandInfo, sources_list: CommandInfo):
    """`declare list [tools|sources]` — one place to see what has been declared."""
    show_tools, show_sources = tools_list.callback, sources_list.callback

    def declared_list(
        kind: str = typer.Argument(
            "all", help="tools, sources, or all (the default; not with --json)."
        ),
        as_json: bool = typer.Option(False, "--json"),
    ) -> None:
        """Everything declared so far: tools and their impact, sources and their tier."""
        if kind not in ("all", "tools", "sources"):
            raise typer.BadParameter("choose tools, sources or all", param_hint="KIND")
        if as_json and kind == "all":
            raise typer.BadParameter("--json needs one kind: tools or sources", param_hint="KIND")
        if kind in ("all", "tools"):
            if kind == "all":
                typer.echo("tools")
            show_tools(as_json=as_json)
        if kind in ("all", "sources"):
            if kind == "all":
                typer.echo("\nsources")
            show_sources(as_json=as_json)

    return declared_list
