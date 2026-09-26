"""The three commands a new user runs, and nothing else.

The rest of the CLI has forty commands across nine sub-apps, which is right for an
operator running a governance programme and wrong for the first ten minutes. Someone
evaluating this should be able to type three words and understand their exposure:

    agentfox init      # set everything up
    agentfox check     # scan the repo and highlight what is ungoverned
    agentfox doctor    # is the runtime configured the way I think it is?

Every one of them is safe to run: `init` is idempotent, `check` reads source without
importing it, and `doctor` only reports. None of them can break a running system, so
nobody has to read the docs before trying one.
"""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ._style import SEVERITY_COLOUR, short_id

console = Console()

_CONFIG_TEMPLATE = """# AgentFox configuration.
# Everything here has a safe default; this file exists so the defaults are visible
# rather than implicit. The [agentfox] table is read from the working directory;
# environment variables (NOMETRIA_*) override it.

[agentfox]
environment = "{environment}"

# Default mode for a policy that does not declare its own. Packs that declare a mode
# keep it (the shipped tool-containment pack declares enforce).
default_policy_mode = "{default_policy_mode}"

# Zero egress: no model call leaves this machine unless you turn it on.
allow_egress = {allow_egress}

# The whole pre-flight pipeline's latency ceiling, in milliseconds.
enforcement_budget_ms = {enforcement_budget_ms}
"""

# What each policy mode means to someone who has not read the PRD.
_MODE_MEANING = {
    "observe": "recorded, nothing blocked",
    "enforce": "violations are blocked now",
}


def _config_text(environment: str) -> str:
    """Render the template from the real Settings defaults, so the file never drifts
    from what the runtime does when the file is absent."""
    from ..config import Settings

    fields = Settings.model_fields
    return _CONFIG_TEMPLATE.format(
        environment=environment,
        default_policy_mode=fields["default_policy_mode"].default,
        allow_egress=str(fields["allow_egress"].default).lower(),
        enforcement_budget_ms=fields["enforcement_budget_ms"].default,
    )


def _session():
    """A session on an initialised database. `init_db` is idempotent, and without it
    a command run before `agentfox init` dies on "no such table"."""
    from ..db import init_db, session_scope

    init_db()
    return session_scope()


#: What `agentfox check` writes in the severity column. Short enough for a table and
#: still a word, so the row survives a terminal with no colour and a pasted log.
_SEVERITY_MARK = {
    "critical": "CRITICAL",
    "high": "high",
    "medium": "medium",
    "low": "low",
    "info": "info",
}


def _fit_path(file: str, line: int, width: int) -> str:
    """``src/agentfox/gateway/routes/inline.py:42`` shortened from the *left*.

    The previous rendering cut from the right, which removed the filename and the
    line number — the two parts of the path that are the point of printing it. When a
    path will not fit, leading directories are dropped and the cut is marked.
    """
    label = f"{file}:{line}"
    if len(label) <= width:
        return label
    parts = label.split("/")
    for index in range(1, len(parts)):
        candidate = "…/" + "/".join(parts[index:])
        if len(candidate) <= width:
            return candidate
    # A single filename longer than the column: keep its end, which carries the
    # extension and the line number.
    return "…" + label[-(width - 1) :]


def _print_next_steps(steps: list[tuple[str, str]]) -> None:
    """A command that ends without a next action makes the reader do the synthesis."""
    table = Table(show_header=False, box=None, padding=(0, 2))
    for command, why in steps:
        table.add_row(f"[bold cyan]{command}[/]", f"[dim]{why}[/]")
    console.print()
    console.print(Panel(table, title="[bold]Next[/]", title_align="left", border_style="dim"))


def init(
    path: Path = typer.Option(
        Path("."), "--path", "-p", help="Where to write agentfox.toml. Default: here."
    ),
    environment: str = typer.Option(
        "development",
        "--env",
        "-e",
        help="Name this deployment: development, staging or production. It decides "
        "how strictly `agentfox doctor` grades authentication.",
    ),
    demo: bool = typer.Option(
        False,
        "--demo",
        help="Also load the demo fixtures: three agents, an eval suite and sample traffic.",
    ),
) -> None:
    """Set everything up. Idempotent, offline, and safe to run twice.

    Creates the database, applies migrations, loads the control catalog and the
    shipped policy packs, each in the mode it declares (baseline and
    eu-ai-act-high-risk observe; tool-containment enforces), and writes a
    agentfox.toml carrying the real runtime defaults so they are visible rather than
    implicit. NOMETRIA_* environment variables override that file.
    """
    from ..compliance import load_catalog, sync_catalog
    from ..config import get_settings
    from ..db import init_db, session_scope
    from ..policy import load_from_dir, save_policy

    settings = get_settings()
    console.print("[bold]Setting up AgentFox[/]")

    init_db()
    console.print(f"  [green]✓[/] database ready  [dim]{settings.database_url}[/]")

    with session_scope() as session:
        summary = sync_catalog(session)
        catalog = load_catalog()
        console.print(
            f"  [green]✓[/] {summary['controls_created'] + summary['controls_updated']} controls "
            f"across {len(catalog.get('frameworks', []))} frameworks  "
            f"[dim]v{catalog.get('version')} ({catalog.get('review_status')})[/]"
        )

        if settings.policies_dir.exists():
            documents = load_from_dir(settings.policies_dir)
            for document in documents:
                save_policy(session, document, author="init", notes="loaded by agentfox init")
            # Say the truth per pack: a blanket "observe mode" was wrong the moment one
            # shipped pack (tool-containment) declared enforce.
            console.print(f"  [green]✓[/] {len(documents)} policy pack(s) loaded")
            for document in sorted(documents, key=lambda d: d.key):
                colour = "red" if document.mode == "enforce" else "yellow"
                meaning = _MODE_MEANING.get(document.mode, "")
                console.print(
                    f"      {document.key:<24} [{colour}]{document.mode}[/]  [dim]{meaning}[/]"
                )
            enforcing = [d.key for d in documents if d.mode == "enforce"]
            if enforcing:
                console.print(
                    f"      [dim]{', '.join(enforcing)} blocks from the start — "
                    "demote with `agentfox policy observe <key>`.[/]"
                )

    config_path = Path(path) / "agentfox.toml"
    if config_path.exists():
        console.print(f"  [dim]·[/] {config_path.name} already exists, left alone")
    else:
        config_path.write_text(_config_text(environment))
        console.print(f"  [green]✓[/] wrote {config_path.name}")

    if demo:
        from ..seed import seed

        with session_scope() as session:
            seed(session)
        console.print("  [green]✓[/] demo fixtures loaded")

    _print_next_steps(
        [
            ("agentfox check", "scan this repo and see what is ungoverned"),
            ("import agentfox; agentfox.auto()", "one line in your entry point"),
            (
                "agentfox tools declare <key> --impact irreversible",
                "declare what each tool can do — this is what still holds when a detector misses",
            ),
            ("agentfox doctor", "check containment readiness, not just detectors"),
        ]
    )


def check(
    path: Path = typer.Argument(Path("."), help="Directory to scan. Default: here."),
    as_json: bool = typer.Option(
        False, "--json", help="Full records for scripts: every site, whole paths, no table."
    ),
    limit: int = typer.Option(
        15, "--limit", "-n", help="How many sites to show, worst first."
    ),
    fail_on_ungoverned: bool = typer.Option(
        False, "--fail", help="Exit non-zero if any model call is ungoverned (for CI)."
    ),
    submit: bool | None = typer.Option(
        None,
        "--submit/--no-submit",
        help="Send a redacted summary (counts and structure only, never file "
        "contents) to a running control plane for a fuller dashboard report. "
        "Optional — omit both flags to be asked interactively.",
    ),
) -> None:
    """Scan a repository and highlight everything worth governing.

    Static only: reads the source, never imports or runs it. Importing the target
    would execute arbitrary code from a repo the operator may not trust, and would
    fail on anything with an import-time side effect — which is most real
    applications. Stays entirely local unless `--submit` (or an interactive "yes")
    opts into sending a redacted summary — see `cli/submit.py`.
    """
    from ..discovery import scan
    from .submit import maybe_submit_report

    report = scan(path)
    if as_json:
        console.print_json(json.dumps(report.to_json(), default=str))
        if submit:
            maybe_submit_report(report, source="check", explicit=True, console=Console(stderr=True))
        raise typer.Exit(1 if fail_on_ungoverned and report.ungoverned else 0)

    console.print(f"[bold]Scanned[/] {report.files_scanned} files in [dim]{report.root}[/]")
    if report.frameworks:
        console.print(f"  [dim]built on:[/] {', '.join(report.frameworks)}")

    calls = len(report.model_calls)
    ungoverned = len(report.ungoverned)
    if calls:
        tone = "red" if ungoverned else "green"
        console.print(
            f"\n  [{tone}]{ungoverned}[/] of [bold]{calls}[/] model call sites are "
            f"ungoverned  [dim]({report.coverage:.0%} covered)[/]"
        )
    counts = report.by_kind()
    other = {k: v for k, v in counts.items() if k != "model_call"}
    if other:
        console.print(
            "  [dim]also found:[/] "
            # Pluralise. "16 shell call" reads as a truncation bug on the first
            # command a new user runs, which is the worst place to have one.
            + ", ".join(
                f"{v} {k.replace('_', ' ')}{'' if v == 1 else 's'}"
                for k, v in other.items()
            )
        )

    ranked = report.ranked(limit)
    if ranked:
        # A budget for the path column, so the paths can be shortened deliberately
        # (from the left, filename last) instead of being cut by the renderer at
        # whatever column happened to be left over.
        where_width = max(28, min(52, console.width // 2))
        table = Table(box=None, padding=(0, 1), header_style="dim")
        table.add_column("severity", no_wrap=True)
        table.add_column("where", no_wrap=True, width=where_width)
        # Fold rather than the default ellipsis: a call site cut to
        # "run_completion(.…" is the one field that says which site this is.
        table.add_column("what", ratio=1, overflow="fold")
        for site in ranked:
            colour = SEVERITY_COLOUR.get(site.severity, "dim")
            # The severity is spelled out, not signalled by the colour of a dot. A
            # hard-coded credential and an ordinary call site rendered as the same
            # glyph in any terminal without colour, and in every copied transcript.
            mark = (
                "[green]governed[/]"
                if site.governed
                else f"[{colour}]{_SEVERITY_MARK.get(site.severity, site.severity)}[/]"
            )
            # No slice: the detail is what tells you which call site this is, and a
            # row ending mid-word reads as a rendering fault, not as a finding.
            where = _fit_path(site.file, site.line, where_width)
            table.add_row(mark, f"[dim]{where}[/]", site.detail)
        console.print()
        console.print(table)
        if len(report.sites) > len(ranked):
            # A hint has to be a command someone can run. "(--limit)" is a flag name.
            target = "" if str(path) == "." else f" {path}"
            # Say WHAT is not shown, not just how many.
            #
            # Found running this against browser-use, a real repository: the
            # headline read "32 of 32 model call sites" and this line read "33
            # more not shown", which cannot both be true of the same population
            # and left the reader to work out that the table also holds the 16
            # shell calls. It counts findings; the headline counts model calls.
            # Naming the unit reconciles them without changing either number.
            hidden = len(report.sites) - len(ranked)
            console.print(
                f"  [dim]{hidden} more finding(s) not shown, across every kind above. "
                f"See all of them:[/] [cyan]agentfox check{target} "
                f"--limit {len(report.sites)}[/]"
            )

    if report.errors:
        console.print(f"\n  [yellow]{len(report.errors)} file(s) could not be parsed[/]")
        for error in report.errors[:3]:
            console.print(f"    [dim]{error}[/]")

    console.print()
    console.print(
        Panel(report.next_step(), border_style="cyan", title="[bold]Next[/]", title_align="left")
    )

    maybe_submit_report(report, source="check", explicit=submit, console=console)

    if fail_on_ungoverned and report.ungoverned:
        raise typer.Exit(1)


def doctor(
    as_json: bool = typer.Option(
        False,
        "--json",
        help="One record per check, for CI. Exits non-zero on a failed check either way.",
    ),
) -> None:
    """Is the runtime configured the way you think it is?

    Reports only — it changes nothing. Every line is a fact about this deployment, and
    each one names the consequence rather than the setting, because "fail_mode=open"
    means nothing to someone who has not read the PRD.
    """
    from ..config import get_settings
    from ..db import session_scope
    from ..guardrails import available_detectors
    from ..models import (
        AccessScopeRule,
        Agent,
        Capability,
        Decision,
        Finding,
        KnowledgeBoundary,
        Tool,
        Trace,
    )
    from ..providers import available_providers

    settings = get_settings()
    checks: list[tuple[str, str, str]] = []

    def add(state: str, what: str, detail: str) -> None:
        checks.append((state, what, detail))

    try:
        from ..db import init_db

        init_db()
        with session_scope() as session:
            agents = session.query(Agent).count()
            traces = session.query(Trace).count()
            decisions = session.query(Decision).count()
            findings = session.query(Finding).filter_by(status="open").count()
            boundaries = session.query(KnowledgeBoundary).count()
            tools_declared = session.query(Tool).count()
            tools_acting = (
                session.query(Tool)
                .filter(Tool.impact.in_(["write", "high_impact", "irreversible"]))
                .count()
            )
            grants = session.query(Capability).count()
            scoped_tables = session.query(AccessScopeRule).count()
            enforcing = (
                session.query(Decision).filter_by(mode="enforce").count() if decisions else 0
            )
        add("ok", "database", f"reachable — {agents} agent(s), {traces} trace(s)")
    except Exception as exc:
        add("bad", "database", f"unreachable: {exc}")
        agents = traces = decisions = findings = boundaries = enforcing = 0
        tools_declared = tools_acting = grants = scoped_tables = 0

    if decisions == 0:
        add(
            "warn",
            "traffic",
            "no decisions recorded — nothing has been governed yet. "
            "Add `agentfox.auto()` to your entry point.",
        )
    elif enforcing == 0:
        add(
            "warn",
            "enforcement",
            f"{decisions} decision(s), all in observe mode — recorded, nothing blocked. "
            "That is the safe default, not a finished configuration.",
        )
    else:
        add("ok", "enforcement", f"{enforcing} of {decisions} decisions enforced")

    # Authentication first: it is the check most likely to be wrong and most costly
    # when it is, and a deployment that fails it does not need to read the rest.
    from ..gateway.auth import header_identity_allowed

    if header_identity_allowed():
        add(
            "warn"
            if settings.environment.lower() in ("development", "dev", "test", "local")
            else "bad",
            "authentication",
            f"the X-Nometria-User header is accepted (environment={settings.environment}, "
            f"auth_mode={settings.auth_mode}) — anyone who can reach this port is any "
            "user they name. Fine locally, unacceptable anywhere else.",
        )
    else:
        add("ok", "authentication", "API tokens required; the identity header is refused")

    # Containment before detection, deliberately. Every published adversarial-robustness
    # result says a determined attacker eventually gets past content inspection; what is
    # left at that moment is what an agent is *allowed to do*. That is declared, not
    # detected, so a deployment that has declared nothing is undefended in the case that
    # actually matters — however many detectors it has loaded.
    if tools_declared == 0:
        # "bad" only once something has actually run: a fresh install has declared
        # nothing because nothing has happened yet, which is a starting state, not a
        # misconfiguration. A deployment with live traffic and no declarations is the
        # real failure, and it gets the hard verdict.
        add(
            "bad" if decisions else "warn",
            "containment",
            "no tools declared — nothing constrains what an agent may do when a detector "
            "misses. Declare them with `agentfox tools declare <key> --impact ...`."
            + (" Traffic is already being governed without them." if decisions else ""),
        )
    elif tools_acting == 0:
        add(
            "warn",
            "containment",
            f"{tools_declared} tool(s) declared, none of them write/high-impact/irreversible "
            "— if this agent can act, its impact tiers are understated and containment "
            "rules cannot fire.",
        )
    elif grants == 0:
        add(
            "warn",
            "containment",
            f"{tools_acting} acting tool(s) declared but no capability grants — least "
            "privilege is unconfigured, so policy is the only thing standing in the way. "
            "Grant them with `agentfox capability grant <agent> <tool> --limit ...`.",
        )
    else:
        add(
            "ok",
            "containment",
            f"{tools_acting} of {tools_declared} tool(s) can act, {grants} capability "
            "grant(s) — an action outside these is refused whether or not a detector fires",
        )

    add(
        "ok" if scoped_tables else "warn",
        "data scope",
        f"{scoped_tables} table(s) declared row-scoped"
        if scoped_tables
        else "no table row-scoping declared — a query across every customer's rows reads "
        "as ordinary. Declare with `agentfox access declare-scope <table> --column ...`.",
    )

    detectors = available_detectors()
    add(
        "ok" if detectors else "bad",
        "detectors",
        f"{len(detectors)} available: {', '.join(sorted(detectors))}",
    )

    providers = available_providers()
    if providers == {"echo"}:
        add(
            "ok",
            "providers",
            "offline only (echo). No model call can leave this machine — set "
            "NOMETRIA_ALLOW_EGRESS=1 and a key to change that.",
        )
    else:
        add("ok", "providers", f"{', '.join(sorted(providers))}")

    add(
        "warn" if settings.fail_mode == "open" else "ok",
        "detector failure",
        "fail-open: a detector that times out lets the request through and records the gap"
        if settings.fail_mode == "open"
        else "fail-closed: a degraded detector blocks the request",
    )

    if boundaries == 0:
        add(
            "warn",
            "answerability",
            "no knowledge boundary declared — nothing stops an agent answering a "
            "question it has no data for.",
        )
    else:
        add("ok", "answerability", f"{boundaries} boundary/boundaries declared")

    if findings:
        add("warn", "findings", f"{findings} open — run `agentfox findings`")
    else:
        add("ok", "findings", "none open")

    failed = any(state == "bad" for state, _w, _d in checks)

    if as_json:
        console.print_json(
            json.dumps([{"state": s, "check": c, "detail": d} for s, c, d in checks])
        )
        # Same exit contract as the table: JSON mode is what CI uses, so it is the
        # mode that most needs to fail on a bad check.
        raise typer.Exit(1 if failed else 0)

    console.print("[bold]Runtime check[/]")
    marks = {"ok": "[green]✓[/]", "warn": "[yellow]![/]", "bad": "[red]✗[/]"}
    table = Table(box=None, padding=(0, 2), show_header=False)
    for state, what, detail in checks:
        table.add_row(marks[state], f"[bold]{what}[/]", detail)
    console.print(table)

    if failed:
        raise typer.Exit(1)


#: Worst first. `agentfox check` advertises this list as ranked by severity, and for
#: a long time it was ordered by creation time instead.
SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}


def findings_cmd(
    severity: str | None = typer.Option(
        None,
        "--severity",
        "-s",
        help="Show only this severity: critical, high, medium, low or info.",
    ),
    limit: int = typer.Option(
        20, "--limit", "-n", help="How many findings to show, worst first."
    ),
    as_json: bool = typer.Option(
        False,
        "--json",
        help="Full records for scripts: whole ids, fingerprints, subjects and timestamps.",
    ),
) -> None:
    """What the platform found. The list `agentfox.auto()` tells you to read.

    Ordered worst first, then most recently seen. A finding that keeps happening is
    one row with a count, not one row per occurrence, so the length of this list is
    the number of distinct problems.
    """
    from sqlalchemy import case, func, select

    from ..models import Finding

    if severity and severity not in SEVERITY_RANK:
        console.print(
            f"[red]unknown severity '{severity}'[/]. Use one of: "
            f"{', '.join(SEVERITY_RANK)}"
        )
        raise typer.Exit(2)

    with _session() as session:
        # Ranked in SQL, not after the fact: sorting the page the database happened to
        # return would show the worst of twenty rows, not the twenty worst rows.
        rank = case(SEVERITY_RANK, value=Finding.severity, else_=9)
        recency = func.coalesce(Finding.last_seen_at, Finding.created_at)
        stmt = select(Finding).where(Finding.status == "open")
        if severity:
            stmt = stmt.where(Finding.severity == severity)
        total = session.scalar(
            select(func.count()).select_from(stmt.subquery())
        )
        rows = [
            {
                "id": f.id,
                "type": f.type,
                "severity": f.severity,
                "title": f.title,
                "subject": f"{f.subject_type}:{f.subject_id}",
                "at": f.created_at.isoformat(),
                "occurrences": f.occurrences,
                "fingerprint": f.fingerprint,
                "last_seen_at": f.last_seen_at.isoformat() if f.last_seen_at else None,
            }
            for f in session.scalars(stmt.order_by(rank, recency.desc()).limit(limit))
        ]

    if as_json:
        console.print_json(json.dumps(rows, default=str))
        return
    if not rows:
        scope = f" at severity '{severity}'" if severity else ""
        console.print(f"[green]No open findings{scope}.[/]")
        return

    # Narrow padding and a merged severity/count column so the title keeps enough
    # width to wrap between words on an 80-column terminal instead of inside one.
    table = Table(box=None, padding=(0, 1), header_style="dim")
    table.add_column("id", no_wrap=True)
    table.add_column("severity", no_wrap=True)
    table.add_column("type", no_wrap=True)
    # No slice: a type cut to "INJECTION.INSTRUCTION_OVER" names a category that does
    # not exist, and nothing can be grepped for it.
    table.add_column("what", ratio=1)
    for row in rows:
        colour = SEVERITY_COLOUR.get(row["severity"], "dim")
        occurrences = row["occurrences"] or 1
        seen = f" [bold]{occurrences}x[/]" if occurrences > 1 else ""
        table.add_row(
            f"[dim]{short_id(row['id'])}[/]",
            f"[{colour}]{row['severity']}[/]{seen}",
            f"[dim]{row['type']}[/]",
            row["title"],
        )
    console.print(table)

    repeats = sum((row["occurrences"] or 1) for row in rows)
    shown = f"{len(rows)} of {total}" if total and total > len(rows) else str(len(rows))
    console.print(
        f"\n  [dim]{shown} open finding(s)"
        + (f", {repeats} occurrences in total" if repeats > len(rows) else "")
        + ".[/]"
    )

    steps: list[tuple[str, str]] = []
    if total and total > len(rows):
        steps.append((f"agentfox findings --limit {total}", "show the rest of them"))
    worst = min(rows, key=lambda r: SEVERITY_RANK.get(r["severity"], 9))["severity"]
    if not severity and worst in ("critical", "high"):
        steps.append((f"agentfox findings --severity {worst}", f"just the {worst} ones"))
    steps.append(("agentfox findings --json", "whole ids, fingerprints and subjects"))
    steps.append(("agentfox doctor", "check the runtime configuration that produced these"))
    steps.append(
        (
            "agentfox serve",
            "control plane on http://127.0.0.1:8080, the full detail view",
        )
    )
    _print_next_steps(steps)


def quickstart() -> None:
    """Print the shortest path from nothing to governed."""
    console.print(
        Panel(
            "\n".join(
                [
                    "[bold]1.[/] [cyan]agentfox init[/]",
                    "   [dim]database, controls, baseline policy in observe mode[/]",
                    "",
                    "[bold]2.[/] Add one line to your entry point:",
                    "   [cyan]import agentfox; agentfox.auto()[/]",
                    "   [dim]every model call is now traced, evaluated and audited[/]",
                    "",
                    "[bold]3.[/] [cyan]agentfox check[/]",
                    "   [dim]see what is still ungoverned[/]",
                    "",
                    "[bold]4.[/] [cyan]agentfox findings[/]",
                    "   [dim]see what it found[/]",
                    "",
                    "[bold]5.[/] [cyan]agentfox policy enforce baseline[/]",
                    "   [dim]when the findings look right — this is the only step that blocks[/]",
                ]
            ),
            title="[bold]AgentFox in five steps[/]",
            title_align="left",
            border_style="cyan",
        )
    )


def register(app: typer.Typer) -> None:
    """Attach the onboarding commands as top-level verbs."""
    app.command(name="init")(init)
    app.command(name="check")(check)
    app.command(name="doctor")(doctor)
    app.command(name="findings")(findings_cmd)
    app.command(name="quickstart")(quickstart)
