"""AgentFox CLI.

The commands a platform engineer runs (``eval gate``, ``policy simulate``) and the
commands a compliance lead runs (``compliance status``, ``evidence export``) are the
same binary against the same API. That is the land-and-expand path in PRD §4.3
expressed as a tool: the engineer installs it for CI, and the CISO finds their view
already there.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .. import __version__
from ._style import SEVERITY_COLOUR, print_unknown_agent

app = typer.Typer(
    name="agentfox",
    help="Agent-native, vendor-neutral governance for AI agents in production.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()

agents_app = typer.Typer(
    help="Find every agent that is running, and who owns it (Pillar 1).",
    no_args_is_help=True,
)
policy_app = typer.Typer(
    help="Write the rules, try them against recorded traffic, then turn them on "
    "(Pillar 6).",
    no_args_is_help=True,
)
eval_app = typer.Typer(
    help="Score an agent, fail the build on a regression, watch for drift (Pillar 4).",
    no_args_is_help=True,
)
audit_app = typer.Typer(
    help="Check that the recorded history has not been altered (Pillar 5).",
    no_args_is_help=True,
)
evidence_app = typer.Typer(
    help="Export a package an auditor can verify without us (Pillar 5).",
    no_args_is_help=True,
)
compliance_app = typer.Typer(
    help="Where this deployment stands against each framework, computed from "
    "telemetry (Pillar 6).",
    no_args_is_help=True,
)
redteam_app = typer.Typer(
    help="Attack your own configuration and score what got through (Pillar 4).",
    no_args_is_help=True,
)
scan_app = typer.Typer(
    help="Snapshot an MCP server's tools and check them for hygiene (Pillar 1).",
    no_args_is_help=True,
)
db_app = typer.Typer(
    help="Apply, roll back and inspect the database schema.", no_args_is_help=True
)
tools_app = typer.Typer(
    help="Declare what each tool can do, so containment has something to reason "
    "over (P9).",
    no_args_is_help=True,
)
access_app = typer.Typer(
    help="Declare which column decides whose row it is, so a query across every "
    "customer stops reading as ordinary (P18).",
    no_args_is_help=True,
)

app.add_typer(agents_app, name="agents")
app.add_typer(policy_app, name="policy")
app.add_typer(eval_app, name="eval")
app.add_typer(audit_app, name="audit")
app.add_typer(evidence_app, name="evidence")
app.add_typer(compliance_app, name="compliance")
app.add_typer(redteam_app, name="redteam")
app.add_typer(scan_app, name="scan")
app.add_typer(tools_app, name="tools")
app.add_typer(access_app, name="access")
app.add_typer(db_app, name="db")

# The three commands a new user runs, registered as top-level verbs. The rest of this
# CLI is right for an operator running a governance programme and wrong for the first
# ten minutes.
from .auth_cli import register as _register_auth  # noqa: E402
from .business_cli import register as _register_business  # noqa: E402
from .capability_cli import register as _register_capability  # noqa: E402
from .controls_cli import register as _register_controls  # noqa: E402
from .mcp_cli import register as _register_mcp  # noqa: E402
from .onboarding import register as _register_onboarding  # noqa: E402
from .quickscan import register as _register_quickscan  # noqa: E402

_register_onboarding(app)
_register_quickscan(app)
_register_auth(app)
_register_controls(app)
_register_business(app)
_register_mcp(app)
_register_capability(app)


def _session():
    from ..db import init_db, session_scope

    init_db()
    return session_scope()


def _emit(payload: Any, as_json: bool) -> None:
    if as_json:
        console.print_json(json.dumps(payload, default=str))


# ---------------------------------------------------------------------------
# Top-level
# ---------------------------------------------------------------------------


@app.command()
def version() -> None:
    """Show the version of everything that takes part in a decision."""
    from ..compliance.catalog import load_catalog
    from ..config import get_settings

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


@app.command()
def seed(
    show_keys: bool = typer.Option(
        False,
        "--show-keys",
        help="Print newly issued agent API keys in full. Keys are shown only once, "
        "when first issued; this flag is the only way to see them.",
    ),
) -> None:
    """Load a demonstrable environment: three agents, policies, controls and an
    eval suite, with traffic already recorded against them."""
    from ..seed import seed as run_seed

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
            "`agentfox seed --show-keys` on a fresh database is the only way to see "
            "them in full.[/]"
        )

    from .onboarding import _print_next_steps

    _print_next_steps(
        [
            ("agentfox demo", "the end-to-end walkthrough against what was just seeded"),
            ("agentfox findings", "what the seeded traffic already raised"),
            ("agentfox capability list", "what each seeded agent is allowed to do"),
            ("agentfox doctor", "check the runtime configuration"),
        ]
    )


@app.command()
def demo() -> None:
    """Run the end-to-end walkthrough (offline)."""
    from ..db import init_db, session_scope
    from ..models import Agent
    from ..seed import register_scripts
    from ..seed import seed as run_seed

    init_db()
    with session_scope() as session:
        if session.query(Agent).count() == 0:
            console.print("[dim]no agents found — seeding first[/]")
            run_seed(session)
    # The offline provider's scripted replies live in process memory, so a demo run
    # against an already-seeded database has to re-register them.
    register_scripts()

    from .demo import run

    run()


@app.command()
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
    uvicorn.run("agentfox.gateway.app:app", host=host, port=port, reload=reload)


# ---------------------------------------------------------------------------
# db (PL-2)
# ---------------------------------------------------------------------------


@db_app.command("upgrade")
def db_upgrade(revision: str = "head") -> None:
    """Apply migrations. This is how a deployed instance is upgraded."""
    from ..db import current_revision, upgrade_db

    before = current_revision()
    upgrade_db(revision)
    after = current_revision()
    console.print(f"[green]migrated[/] {before or 'empty'} → [bold]{after}[/]")


@db_app.command("downgrade")
def db_downgrade(revision: str = typer.Argument(..., help="Target revision, or 'base'.")) -> None:
    """Roll back migrations. Every migration ships with a tested downgrade."""
    from ..db import current_revision, downgrade_db

    before = current_revision()
    downgrade_db(revision)
    console.print(f"[yellow]rolled back[/] {before} → [bold]{current_revision() or 'base'}[/]")


@db_app.command("current")
def db_current() -> None:
    """Show the applied schema revision."""
    from ..db import current_revision

    revision = current_revision()
    console.print(f"schema revision: [bold]{revision or 'none — run `agentfox db upgrade`'}[/]")


# ---------------------------------------------------------------------------
# agents
# ---------------------------------------------------------------------------


@agents_app.command("list")
def agents_list(as_json: bool = typer.Option(False, "--json")) -> None:
    """List every agent, registered or shadow."""
    from sqlalchemy import select

    from ..models import Agent
    from ..registry.service import inventory

    with _session() as session:
        agents = list(session.scalars(select(Agent).order_by(Agent.slug)))
        summary = inventory(session)
        rows = [
            {
                "slug": a.slug,
                "environment": a.environment,
                "risk_tier": a.risk_tier,
                "registered": a.registered,
                "owner": a.owner_email,
                "framework": a.framework,
            }
            for a in agents
        ]
    if as_json:
        _emit({"agents": rows, "inventory": summary}, True)
        return
    table = Table(box=None, pad_edge=False)
    for column in ("agent", "env", "risk", "registered", "owner", "framework"):
        table.add_column(column, style="bold" if column == "agent" else None)
    for row in rows:
        table.add_row(
            row["slug"],
            row["environment"],
            row["risk_tier"],
            "[green]yes[/]" if row["registered"] else "[red]SHADOW[/]",
            row["owner"] or "[red]unowned[/]",
            row["framework"] or "—",
        )
    console.print(table)
    console.print(
        f"  [dim]{summary['agents']} agents · {summary['shadow']} shadow · "
        f"{summary['unowned']} unowned · {summary['lineage_edges']} lineage edges[/]"
    )


@agents_app.command("discover")
def agents_discover() -> None:
    """Sweep for shadow agents, unowned agents, registry drift, identity posture and
    delegation cycles/depth."""
    from ..identity import assess_posture
    from ..registry.service import (
        assess_delegation,
        attest_registry,
        derive_lineage,
        detect_shadow_agents,
        unowned_agents,
    )

    with _session() as session:
        edges = derive_lineage(session)
        shadows = detect_shadow_agents(session)
        unowned = unowned_agents(session)
        drift = attest_registry(session)
        posture = assess_posture(session)
        delegation = assess_delegation(session)
    console.print(f"  lineage edges derived   {edges}")
    console.print(f"  shadow agents           [red]{len(shadows)}[/]")
    console.print(f"  unowned agents          [yellow]{len(unowned)}[/]")
    console.print(f"  registry drift findings [yellow]{len(drift)}[/]")
    console.print(f"  identity posture issues [yellow]{len(posture)}[/]")
    console.print(f"  delegation findings     [yellow]{len(delegation)}[/]")
    for shadow in shadows:
        console.print(
            f"    [red]shadow[/] {shadow['slug']} — {shadow['calls']} calls "
            f"in {shadow['environment']}"
        )


@agents_app.command("lineage")
def agents_lineage(slug: str, depth: int = 2) -> None:
    """Show what an agent reaches — the blast radius."""
    from ..registry.service import derive_lineage, lineage

    with _session() as session:
        derive_lineage(session, slug)
        graph = lineage(session, slug, depth)
    console.print(f"[bold]{slug}[/] — blast radius {graph['blast_radius']}")
    for link in graph["links"]:
        console.print(
            f"  {link['source']} [dim]--{link['relation']}-->[/] {link['target']} "
            f"[dim](observed {link['observed_count']}×)[/]"
        )


@agents_app.command("quarantine")
def agents_quarantine(slug: str, reason: str = typer.Option("", "--reason", "-r")) -> None:
    """Stop an agent while you investigate. Reversible and audited."""
    _agent_state(slug, "quarantined", reason)


@agents_app.command("kill")
def agents_kill(slug: str, reason: str = typer.Option("", "--reason", "-r")) -> None:
    """Stop an agent now."""
    _agent_state(slug, "killed", reason)


@agents_app.command("resume")
def agents_resume(slug: str, reason: str = typer.Option("", "--reason", "-r")) -> None:
    """Restart a stopped agent."""
    _agent_state(slug, "active", reason)


@agents_app.command("controls")
def agents_controls() -> None:
    """Show every agent that is not in the active state."""
    from ..registry.control import all_controls

    with _session() as session:
        rows = all_controls(session)
    if not rows:
        console.print("[green]all agents active[/]")
        return
    table = Table(box=None, pad_edge=False)
    for column in ("agent", "state", "reason", "by", "when"):
        table.add_column(column, style="bold" if column == "agent" else None)
    for row in rows:
        colour = {"killed": "red", "quarantined": "yellow"}.get(row["state"], "green")
        table.add_row(
            row["agent"],
            f"[{colour}]{row['state']}[/]",
            row["reason"] or "—",
            row["actor"] or "—",
            (row["changed_at"] or "")[:19],
        )
    console.print(table)


def _agent_state(slug: str, state: str, reason: str) -> None:
    from ..registry.control import UnknownAgent, set_state

    with _session() as session:
        try:
            control = set_state(session, slug, state, reason=reason, actor="cli")
        except UnknownAgent as exc:
            print_unknown_agent(console, session, slug)
            raise typer.Exit(1) from exc
        previous, now = control.previous_state, control.state
    colour = {"killed": "red", "quarantined": "yellow"}.get(now, "green")
    console.print(
        f"[bold]{slug}[/] {previous or 'active'} → [{colour}]{now}[/]"
        + (f"  [dim]{reason}[/]" if reason else "")
    )


# ---------------------------------------------------------------------------
# policy
# ---------------------------------------------------------------------------


@policy_app.command("list")
def policy_list() -> None:
    """List policies and their enforcement mode."""
    from sqlalchemy import select

    from ..models import Policy, PolicyBinding, PolicyVersion

    with _session() as session:
        table = Table(box=None, pad_edge=False)
        for column in ("policy", "version", "mode", "rules"):
            table.add_column(column, style="bold" if column == "policy" else None)
        for policy in session.scalars(select(Policy).order_by(Policy.key)):
            latest = session.scalars(
                select(PolicyVersion)
                .where(PolicyVersion.policy_id == policy.id)
                .order_by(PolicyVersion.version.desc())
            ).first()
            if latest is None:
                continue
            binding = session.scalars(
                select(PolicyBinding).where(
                    PolicyBinding.policy_version_id == latest.id,
                    PolicyBinding.effective_to.is_(None),
                )
            ).first()
            mode = binding.mode if binding else "unbound"
            table.add_row(
                policy.key,
                f"v{latest.version}",
                f"[green]{mode}[/]" if mode == "enforce" else f"[yellow]{mode}[/]",
                str(len((latest.compiled_json or {}).get("rules", []))),
            )
        console.print(table)


@policy_app.command("lint")
def policy_lint() -> None:
    """Lint the policy hierarchy (P12-4). Exits 1 on critical or high findings.

    This is the half of hierarchical policy that produces the 87% misconfiguration
    reduction — composition without a linter just moves the confusion somewhere
    harder to see.
    """
    from ..policy import lint_all

    with _session() as session:
        report = lint_all(session)

    if not report["findings"]:
        console.print("[green]no policy issues[/]")
        return

    table = Table(box=None, pad_edge=False)
    for column in ("severity", "code", "rule", "level", "message"):
        table.add_column(column, style="bold" if column == "code" else None)
    order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    for finding in sorted(report["findings"], key=lambda f: order.get(f["severity"], 9)):
        colour = SEVERITY_COLOUR.get(finding["severity"], "dim")
        table.add_row(
            f"[{colour}]{finding['severity']}[/]",
            finding["code"],
            finding["rule_id"],
            finding["level"] or "—",
            finding["message"][:74],
        )
    console.print(table)
    console.print(f"  [dim]{report['counts']}[/]")

    if not report["passed"]:
        console.print("\n[bold red]LINT FAIL[/] — critical/high findings block the build")
        raise typer.Exit(1)
    console.print("\n[green]LINT PASS[/] [dim](advisory findings only)[/]")


@policy_app.command("effective")
def policy_effective(
    agent: str | None = None,
    team: str | None = None,
    user: str | None = None,
    environment: str | None = typer.Option(
        None,
        "--environment",
        help="Environment to resolve for. Defaults to the configured environment "
        "(NOMETRIA_ENVIRONMENT), which is what the runtime itself uses.",
    ),
) -> None:
    """Show the policy actually in force for a subject, and where each rule came from.

    Opacity is what makes layered policy dangerous, so the resolver explains itself.
    """
    from ..config import get_settings
    from ..policy import effective_for

    environment = environment or get_settings().environment
    with _session() as session:
        effective = effective_for(
            session, agent_slug=agent, environment=environment, team=team, user=user
        )
        explanation = effective.explain()

    console.print(
        f"[bold]effective policy[/] in [bold]{environment}[/] — "
        f"mode [bold]{explanation['mode']}[/], "
        f"default {explanation['default_effect']}"
    )
    console.print(f"  [dim]layers: {', '.join(explanation['layers']) or 'none'}[/]\n")

    table = Table(box=None, pad_edge=False)
    for column in ("rule", "effect", "from", "overrides"):
        table.add_column(column, style="bold" if column == "rule" else None)
    for rule in explanation["rules"]:
        table.add_row(
            rule["rule_id"],
            rule["effect"],
            rule["source"],
            ", ".join(rule["overrides"]) or "—",
        )
    console.print(table)

    if explanation["rejected"]:
        console.print("\n[bold yellow]rejected layer rules[/]")
        for rejected in explanation["rejected"]:
            console.print(
                f"  [yellow]{rejected['rule_id']}[/] at {rejected['level']}:"
                f"{rejected['scope']} — {rejected['reason'][:88]}"
            )


@policy_app.command("simulate")
def policy_simulate(
    file: Path = typer.Option(..., "--file", "-f", help="Candidate policy YAML."),
    agent: str | None = None,
    since_days: int = 30,
    limit: int = 1000,
) -> None:
    """Replay recorded traffic against a candidate policy (P2-7).

    Exits non-zero when the change would newly block production traffic, so it can
    gate a policy PR the same way `eval gate` gates a code PR.
    """
    from ..policy import PolicyDocument, record_simulation, simulate

    candidate = PolicyDocument.from_yaml(file.read_text())
    with _session() as session:
        diff = simulate(
            session,
            candidate,
            agent_slug=agent,
            since=dt.datetime.now(dt.UTC) - dt.timedelta(days=since_days),
            limit=limit,
        )
        record_simulation(session, candidate, diff, run_by="cli")

    console.print(f"[bold]{candidate.key}[/] simulated against {diff.replayed} decisions")
    console.print(f"  unchanged        {diff.unchanged}")
    console.print(f"  newly blocked    [red]{len(diff.newly_blocked)}[/]")
    console.print(f"  newly escalated  [yellow]{len(diff.newly_escalated)}[/]")
    console.print(f"  newly allowed    [green]{len(diff.newly_allowed)}[/]")
    for record in diff.newly_blocked[:10]:
        console.print(
            f"    [red]would block[/] {record['agent']} {record['surface']} "
            f"{record['tool'] or ''} — {(record['reasons'] or [''])[0][:80]}"
        )
    if diff.risky:
        console.print(
            "\n[bold red]This change would block production traffic. "
            "Review before promoting to enforce.[/]"
        )
        raise typer.Exit(1)
    console.print("\n[green]No production traffic would newly block.[/]")


@policy_app.command("enforce")
def policy_enforce(key: str) -> None:
    """Promote a policy from observe to enforce."""
    _set_mode(key, "enforce")


@policy_app.command("observe")
def policy_observe(key: str) -> None:
    """Demote a policy from enforce to observe."""
    _set_mode(key, "observe")


def _set_mode(key: str, mode: str) -> None:
    from sqlalchemy import select

    from ..audit import chain
    from ..models import Policy
    from ..policy import set_mode

    with _session() as session:
        binding = set_mode(session, key, mode)
        if binding is None:
            # "unknown policy" with no list leaves the reader guessing at a key they
            # have never seen written down.
            known = sorted(p.key for p in session.scalars(select(Policy)))
            console.print(f"[red]unknown policy '{key}'[/]")
            if known:
                console.print(f"  known policies: {', '.join(known)}")
                console.print("  [dim]`agentfox policy list` shows each one's mode.[/]")
            else:
                console.print(
                    "  no policies loaded yet. Run `agentfox init` to load the shipped packs."
                )
            raise typer.Exit(1)
        chain.append(
            session,
            f"policy.mode_{mode}",
            actor_type="user",
            actor_id="cli",
            subject_type="policy",
            subject_id=key,
            payload={"mode": mode},
        )
    console.print(f"[green]{key}[/] → [bold]{mode}[/]")


@policy_app.command("validate")
def policy_validate(file: Path) -> None:
    """Lint and compile a policy without saving it."""
    from ..policy import PolicyDocument, compile_to_rego

    try:
        doc = PolicyDocument.from_yaml(file.read_text())
    except Exception as exc:
        console.print(f"[red]invalid:[/] {exc}")
        raise typer.Exit(1) from exc
    console.print(
        f"[green]valid[/] — {doc.key} v{doc.version}, {len(doc.rules)} rules, mode={doc.mode}"
    )
    console.print(f"  controls: {sorted({c for r in doc.rules for c in r.controls})}")
    console.print(f"  [dim]compiles to {len(compile_to_rego(doc).splitlines())} lines of Rego[/]")


# ---------------------------------------------------------------------------
# eval
# ---------------------------------------------------------------------------


def _unknown_suite(session: Any, suite: str) -> None:
    """Name the suites that do exist.

    A required positional whose valid values live in a database table is
    undiscoverable otherwise — `policy enforce` already lists its options on the
    same mistake, and there is no reason this one should not.
    """
    from sqlalchemy import select

    from ..models import EvalSuite

    known = sorted(k for k in session.scalars(select(EvalSuite.key)))
    console.print(f"[red]unknown suite '{suite}'[/]")
    if known:
        console.print(f"  known suites: {', '.join(known)}")
    else:
        console.print("  no suites exist yet — `agentfox seed` creates one to try.")


@eval_app.command("suites")
def eval_suites() -> None:
    """List the evaluation suites in this deployment."""
    from sqlalchemy import func, select

    from ..models import EvalCase, EvalSuite

    with _session() as session:
        counts = dict(
            session.execute(
                select(EvalCase.suite_id, func.count()).group_by(EvalCase.suite_id)
            ).all()
        )
        rows = [
            (suite.key, suite.name or "", counts.get(suite.id, 0))
            for suite in session.scalars(select(EvalSuite).order_by(EvalSuite.key))
        ]
    if not rows:
        console.print("[dim]no evaluation suites — `agentfox seed` creates one to try.[/]")
        return
    table = Table(box=None, pad_edge=False)
    for column in ("suite", "name", "cases"):
        table.add_column(column)
    for key, name, cases in rows:
        table.add_row(key, name, str(cases))
    console.print(table)


@eval_app.command("run")
def eval_run(
    suite: str,
    provider: str = "echo",
    model: str = "echo-1",
    agent: str | None = None,
    scorers: str | None = typer.Option(None, help="Comma-separated scorer keys."),
) -> None:
    """Run an evaluation suite."""
    from sqlalchemy import select

    from ..evaluation.runner import NativeEvalRunner, fit_envelope
    from ..models import EvalSuite

    keys = [s.strip() for s in scorers.split(",")] if scorers else None
    with _session() as session:
        record = session.scalar(select(EvalSuite).where(EvalSuite.key == suite))
        if record is None:
            _unknown_suite(session, suite)
            raise typer.Exit(1)
        target: dict[str, Any] = {"provider": provider, "model": model}
        if agent:
            target["agent"] = agent
        run = NativeEvalRunner().run(
            session,
            record,
            target,
            keys,
            envelope=fit_envelope(session, agent) if agent else None,
        )
        summary = run.summary_json
        run_id = run.id
    _print_eval_summary(suite, summary, run_id)


def _print_eval_summary(suite: str, summary: dict[str, Any], run_id: str | None = None) -> None:
    console.print(
        f"[bold]{suite}[/] — {summary.get('cases')} cases, {summary.get('errors')} errors"
    )
    # Without this the run → baseline → gate workflow has a hole in the middle:
    # `eval baseline` takes a run id that nothing in the CLI ever printed.
    if run_id:
        console.print(f"  [dim]run {run_id} · `agentfox eval baseline {run_id}` to pin it[/]")
    table = Table(box=None, pad_edge=False)
    for column in ("scorer", "mean", "min", "max", "pass rate"):
        table.add_column(
            column,
            justify="right" if column != "scorer" else None,
            style="bold" if column == "scorer" else None,
        )
    for key, stats in (summary.get("scorers") or {}).items():
        rate = stats.get("pass_rate")
        table.add_row(
            key,
            f"{stats['mean']:.3f}",
            f"{stats['min']:.3f}",
            f"{stats['max']:.3f}",
            f"{rate:.0%}" if rate is not None else "—",
        )
    console.print(table)


@eval_app.command("gate")
def eval_gate(
    suite: str,
    provider: str = "echo",
    model: str = "echo-1",
    baseline: str | None = typer.Option(None, help="Baseline run id."),
    min_pass_rate: float | None = None,
    junit: Path | None = typer.Option(None, help="Write JUnit XML here."),
    sarif: Path | None = typer.Option(None, help="Write SARIF here."),
) -> None:
    """Run the suite and fail the build on regression (P4-1). Exits 1 on failure."""
    from sqlalchemy import select

    from ..evaluation import gate, to_junit, to_sarif
    from ..evaluation.runner import NativeEvalRunner
    from ..models import EvalSuite

    with _session() as session:
        record = session.scalar(select(EvalSuite).where(EvalSuite.key == suite))
        if record is None:
            _unknown_suite(session, suite)
            raise typer.Exit(1)
        run = NativeEvalRunner().run(session, record, {"provider": provider, "model": model})
        result = gate(session, run, baseline, min_pass_rate=min_pass_rate)
        junit_xml = to_junit(result, suite)
        sarif_json = to_sarif(result)
        summary = run.summary_json
        run_id = run.id

    _print_eval_summary(suite, summary, run_id)
    if junit:
        junit.write_text(junit_xml)
        console.print(f"  [dim]JUnit → {junit}[/]")
    if sarif:
        sarif.write_text(sarif_json)
        console.print(f"  [dim]SARIF → {sarif}[/]")

    if result.passed:
        console.print("\n[bold green]GATE PASS[/]")
        # A gate with no baseline and no floor cannot fail, whatever the scores
        # say. Left unsaid, the first CI run prints GATE PASS and the team
        # believes they have a regression gate when they have an empty one.
        if result.baseline_run_id is None and min_pass_rate is None:
            console.print(
                "  [yellow]nothing to fail against[/] — no baseline and no --min-pass-rate, "
                "so this run could not have failed.\n"
                f"  [dim]arm it: `agentfox eval baseline {run_id}`, or pass "
                "--min-pass-rate.[/]"
            )
        return
    console.print("\n[bold red]GATE FAIL[/]")
    for regression in result.regressions:
        console.print(f"  [red]regression[/] {regression.message}")
    for failure in result.absolute_failures:
        console.print(f"  [red]threshold[/]  {failure['message']}")
    raise typer.Exit(result.exit_code)


@eval_app.command("baseline")
def eval_baseline(run_id: str, label: str = "main") -> None:
    """Mark a run as the regression baseline."""
    from ..evaluation import set_baseline
    from ..models import EvalRun

    with _session() as session:
        run = session.get(EvalRun, run_id)
        if run is None:
            console.print(f"[red]unknown run '{run_id}'[/]")
            raise typer.Exit(1)
        baseline = set_baseline(session, run, label)
    console.print(f"[green]baseline[/] {baseline.id} → run {run_id} ({label})")


@eval_app.command("drift")
def eval_drift(agent: str, scorer: str = "groundedness") -> None:
    """Compare recent production scores against the baseline window."""
    from ..evaluation import compute_drift

    with _session() as session:
        report = compute_drift(session, agent, scorer)
    if report is None:
        console.print("[yellow]insufficient online samples[/] — run `agentfox eval online` first")
        return
    data = report.to_json()
    console.print(
        f"[bold]{agent}[/] · {scorer}  "
        f"PSI [bold]{data['psi']}[/] ({data['band']})  KS {data['ks']}  "
        f"mean {data['mean_baseline']} → {data['mean_current']}"
    )
    if data["drifted"]:
        console.print("[bold red]DRIFT DETECTED[/]")


@eval_app.command("online")
def eval_online(agent: str, since_days: int = 7, rate: float | None = None) -> None:
    """Sample production traffic and score it with the offline scorers (P4-2)."""
    from ..evaluation import sample_production

    with _session() as session:
        run = sample_production(
            session,
            agent,
            since=dt.datetime.now(dt.UTC) - dt.timedelta(days=since_days),
            rate=rate,
        )
        summary = run.summary_json if run else None
    if summary is None:
        console.print("[yellow]no production traffic matched the window[/]")
        return
    console.print(
        f"sampled [bold]{summary.get('sampled')}[/] of "
        f"{summary.get('population')} traces "
        f"(rate {summary.get('sample_rate')})"
    )
    _print_eval_summary(f"online:{agent}", summary)


# ---------------------------------------------------------------------------
# audit / evidence
# ---------------------------------------------------------------------------


@audit_app.command("verify")
def audit_verify(start: int | None = None, end: int | None = None) -> None:
    """Verify the tamper-evident audit chain (P5-2). Exits 1 if broken."""
    from ..audit import chain

    with _session() as session:
        stats = chain.chain_stats(session)
        result = chain.verify_range(session, start, end)

    console.print(
        f"chain: [bold]{stats['entries']}[/] entries, head seq "
        f"{stats['head_seq']}, {stats['checkpoints']} checkpoints"
    )
    if result.valid:
        console.print(
            f"[bold green]CHAIN INTACT[/] — {result.entries_checked} entries "
            f"verified (seq {result.first_seq}..{result.last_seq})"
        )
        return
    console.print(f"[bold red]CHAIN TAMPERED[/] — {len(result.breaks)} break(s)")
    for issue in result.breaks[:10]:
        console.print(f"  [red]seq {issue.seq}[/] {issue.kind}: {issue.detail}")
    for failure in result.checkpoint_failures[:5]:
        console.print(f"  [red]checkpoint seq {failure['seq']}[/] {failure['reason']}")
    raise typer.Exit(1)


@audit_app.command("checkpoint")
def audit_checkpoint() -> None:
    """Write a signed checkpoint over the current chain head."""
    from ..audit import chain

    with _session() as session:
        record = chain.checkpoint_now(session)
        if record is None:
            console.print("[yellow]chain is empty[/]")
            return
        console.print(f"[green]checkpoint[/] seq {record.seq} digest {record.digest[:16]}…")


def _evidence_period(
    from_: str | None, to: str | None, since_days: int
) -> tuple[dt.datetime, dt.datetime | None]:
    """Resolve the package's period from either an explicit range or a lookback.

    An auditor asks for "August", not "the last 47 days", so an explicit range is the
    honest interface and the HTTP API already took one. A bare date on ``--to`` covers
    that whole day: asking for `--to 2026-08-17` and silently getting midnight would
    drop a day of evidence from a package someone signs.
    """
    if from_ is None and to is None:
        return dt.datetime.now(dt.UTC) - dt.timedelta(days=since_days), None

    def parse(value: str, *, end_of_day: bool) -> dt.datetime:
        try:
            moment = dt.datetime.fromisoformat(value)
        except ValueError as exc:
            raise typer.BadParameter(
                f"{value!r} is not a date. Use YYYY-MM-DD, or a full ISO-8601 timestamp."
            ) from exc
        if len(value.strip()) == 10 and end_of_day:
            moment = moment.replace(hour=23, minute=59, second=59, microsecond=999999)
        return moment if moment.tzinfo else moment.replace(tzinfo=dt.UTC)

    period_to = parse(to, end_of_day=True) if to is not None else dt.datetime.now(dt.UTC)
    period_from = (
        parse(from_, end_of_day=False)
        if from_ is not None
        else period_to - dt.timedelta(days=since_days)
    )
    if period_from >= period_to:
        raise typer.BadParameter(f"--from ({period_from:%Y-%m-%d}) is not before --to")
    return period_from, period_to


@evidence_app.command("export")
def evidence_export(
    agent: list[str] = typer.Option(None, "--agent", help="Repeatable; default all."),
    from_: str | None = typer.Option(
        None, "--from", help="Start of the period, YYYY-MM-DD or ISO-8601. Default: --since-days."
    ),
    to: str | None = typer.Option(
        None, "--to", help="End of the period, inclusive of a whole day given as YYYY-MM-DD."
    ),
    since_days: int = 30,
    control: list[str] = typer.Option(None, "--control", help="Repeatable; default all."),
    requested_by: str = "cli",
) -> None:
    """Build an auditor-ready evidence package (P5-3)."""
    from ..audit import evidence

    period_from, period_to = _evidence_period(from_, to, since_days)
    with _session() as session:
        package = evidence.build(
            session,
            agents=list(agent) if agent else ["*"],
            controls=list(control) if control else ["*"],
            period_from=period_from,
            period_to=period_to,
            requested_by=requested_by,
        )
        path = package.path
        counts = package.manifest_json["counts"]
        valid = package.chain_verification_json.get("valid")

    console.print(f"[green]evidence package[/] {path}")
    covered_to = period_to or dt.datetime.now(dt.UTC)
    console.print(f"  period                   {period_from:%Y-%m-%d} → {covered_to:%Y-%m-%d}")
    for key, value in counts.items():
        console.print(f"  {key.replace('_', ' '):<24} {value}")
    console.print(
        f"  chain verification       "
        f"[{'green' if valid else 'red'}]{'valid' if valid else 'INVALID'}[/]"
    )
    console.print("\n[dim]Verify independently: unzip, then `python3 verify_chain.py`[/]")


# ---------------------------------------------------------------------------
# compliance
# ---------------------------------------------------------------------------


@compliance_app.command("sync")
def compliance_sync() -> None:
    """Load the control catalog and obligation calendar from YAML."""
    from ..compliance.catalog import sync_catalog, sync_obligations

    with _session() as session:
        catalog = sync_catalog(session)
        obligations = sync_obligations(session)
    console.print(
        f"[green]catalog[/] v{catalog['version']} — "
        f"{catalog['controls_created']} created, "
        f"{catalog['controls_updated']} updated, "
        f"{catalog['mappings']} mappings "
        f"([yellow]{catalog['review_status']}[/])"
    )
    console.print(f"[green]obligations[/] {obligations}")


@compliance_app.command("compute")
def compliance_compute(window_days: int = 30) -> None:
    """Recompute control status from telemetry (P6-4)."""
    from ..compliance import compute_all, posture

    with _session() as session:
        statuses = compute_all(session, window_days)
        overall = posture(session)
    console.print(f"computed [bold]{len(statuses)}[/] controls over {window_days} days")
    counts = overall["counts"]
    console.print(
        f"  [green]{counts['effective']} effective[/] · "
        f"[yellow]{counts['degraded']} degraded[/] · "
        f"[red]{counts['failing']} failing[/] · "
        f"[dim]{counts['not_implemented']} not implemented[/]"
    )


@compliance_app.command("status")
def compliance_status(framework: str | None = None, verbose: bool = False) -> None:
    """Show control posture, optionally for one framework."""
    from sqlalchemy import select

    from ..compliance import (
        controls_for_framework,
        framework_coverage,
        latest_statuses,
        posture,
    )
    from ..models import Control

    with _session() as session:
        overall = posture(session, framework)
        statuses = latest_statuses(session)
        coverage = framework_coverage(session, framework) if framework else None
        controls = {c.key: c for c in session.scalars(select(Control))}
        in_scope = (
            {c["key"] for c in controls_for_framework(session, framework)} if framework else None
        )

    title = framework or "all frameworks"
    counts = overall["counts"]
    console.print(f"[bold]{title}[/] — {overall['controls']} controls")
    console.print(
        f"  [green]{counts['effective']} effective[/] · "
        f"[yellow]{counts['degraded']} degraded[/] · "
        f"[red]{counts['failing']} failing[/] · "
        f"[dim]{counts['not_implemented']} not implemented[/]"
    )
    if overall["effectiveness"] is not None:
        console.print(f"  effectiveness {overall['effectiveness']:.0%}")

    if verbose:
        table = Table(box=None, pad_edge=False)
        for column in ("control", "status", "rationale"):
            table.add_column(column, style="bold" if column == "control" else None)
        for key in sorted(statuses):
            if in_scope is not None and key not in in_scope:
                continue
            status = statuses[key]
            colour = {"effective": "green", "degraded": "yellow", "failing": "red"}.get(
                status.status, "dim"
            )
            table.add_row(key, f"[{colour}]{status.status}[/]", status.rationale[:88])
        console.print(table)
        if in_scope is not None:
            console.print(
                f"  [dim]{len(in_scope)} of {len(controls)} catalog controls map to {framework}[/]"
            )
        else:
            console.print(f"  [dim]{len(controls)} controls in catalog[/]")

    if coverage:
        console.print(
            f"\n  mappings: {coverage['mappings_reviewed']} reviewed, "
            f"[yellow]{coverage['mappings_draft']} draft[/]"
        )
        if coverage["declared_gaps"]:
            console.print("  [bold]declared gaps — not covered by this product:[/]")
            for gap in coverage["declared_gaps"]:
                console.print(f"    [dim]· {gap}[/]")
        console.print(f"\n  [yellow]{coverage['caveat']}[/]")


@compliance_app.command("validate")
def compliance_validate() -> None:
    """Check the control catalog and obligation calendar are internally consistent.

    Read-only and offline: parses controls.yaml and obligations.yaml under the
    configured compliance directory and never touches the database. Exits 1 on any
    problem, so it can gate a catalog change the way `policy lint` gates a policy.
    """
    import yaml

    from ..compliance.catalog import catalog_path, obligations_path
    from ..compliance.status import RULE_KINDS

    problems: list[str] = []

    def _load(path: Path) -> dict[str, Any]:
        if not path.exists():
            problems.append(f"{path}: not found")
            return {}
        try:
            data = yaml.safe_load(path.read_text()) or {}
        except yaml.YAMLError as exc:
            problems.append(f"{path.name}: does not parse — {exc}")
            return {}
        if not isinstance(data, dict):
            problems.append(f"{path.name}: top level must be a mapping")
            return {}
        return data

    catalog_file = catalog_path()
    catalog = _load(catalog_file)
    frameworks = catalog.get("frameworks") or {}
    if not isinstance(frameworks, dict) or not frameworks:
        if catalog:
            problems.append("controls.yaml: no frameworks declared")
        frameworks = {}
    known = set(frameworks)
    review_status = catalog.get("review_status", "draft")

    controls = catalog.get("controls") or []
    seen: set[str] = set()
    mappings = 0
    for index, spec in enumerate(controls):
        if not isinstance(spec, dict):
            problems.append(f"controls[{index}]: not a mapping")
            continue
        key = spec.get("key")
        label = key or f"controls[{index}]"
        if not key:
            problems.append(f"{label}: missing key")
        elif key in seen:
            problems.append(f"{key}: duplicate control key")
        else:
            seen.add(key)
        for field in ("title", "objective", "family", "status_rule"):
            if not spec.get(field):
                problems.append(f"{label}: missing {field}")
        rule = spec.get("status_rule")
        if rule and not isinstance(rule, dict):
            problems.append(f"{label}: status_rule must be a mapping")
        elif rule:
            # evaluate_control defaults a missing kind to presence, so that is valid;
            # an unknown one silently falls back to presence, which is not.
            kind = rule.get("kind", "presence")
            if kind not in RULE_KINDS:
                problems.append(
                    f"{label}: status_rule kind {kind!r} is not one compute understands "
                    f"({', '.join(sorted(RULE_KINDS))})"
                )
        spec_mappings = spec.get("mappings") or {}
        if not isinstance(spec_mappings, dict):
            problems.append(f"{label}: mappings must be a mapping of framework → references")
            continue
        for framework, references in spec_mappings.items():
            if framework not in known:
                problems.append(f"{label}: mapped to undeclared framework {framework!r}")
            if not isinstance(references, list) or not all(
                isinstance(r, str) and r.strip() for r in references
            ):
                problems.append(f"{label}: {framework} references must be a list of strings")
                continue
            mappings += len(references)

    for framework in catalog.get("gaps") or {}:
        if framework not in known:
            problems.append(f"gaps: undeclared framework {framework!r}")

    obligations_file = obligations_path()
    obligations = _load(obligations_file).get("obligations") or []
    for index, spec in enumerate(obligations):
        if not isinstance(spec, dict):
            problems.append(f"obligations[{index}]: not a mapping")
            continue
        label = f"obligation {spec.get('reference') or f'[{index}]'}"
        if not spec.get("reference"):
            problems.append(f"{label}: missing reference")
        framework = spec.get("framework")
        if not framework:
            problems.append(f"{label}: missing framework")
        elif framework not in known:
            problems.append(f"{label}: undeclared framework {framework!r}")

    # Per-mapping review status lives in the database (set by `review_mapping`); the
    # file carries one catalog-wide status, which is what a fresh sync starts from.
    reviewed = mappings if review_status == "reviewed" else 0
    console.print(
        f"[bold]control catalog[/] v{catalog.get('version', '?')}  [dim]{catalog_file}[/]"
    )
    console.print(f"  controls     {len(controls)}")
    console.print(f"  frameworks   {len(known)}")
    console.print(
        f"  mappings     {mappings}  ([yellow]{mappings - reviewed} draft[/], "
        f"{reviewed} reviewed)"
    )
    console.print(f"  obligations  {len(obligations)}")

    if problems:
        console.print(f"\n[bold red]{len(problems)} problem(s)[/]")
        for problem in problems:
            console.print(f"  [red]✗[/] {problem}")
        raise typer.Exit(1)
    console.print("\n[green]catalog valid[/]")


@compliance_app.command("review-packet")
def compliance_review_packet(
    framework: str = typer.Option(..., "--framework", help="Framework key, e.g. eu-ai-act."),
    out: Path | None = typer.Option(None, "--out", help="Write markdown here instead of stdout."),
) -> None:
    """Everything a qualified reviewer needs to sign off one framework, in one file (B.6).

    Every mapping ships `DRAFT — UNVERIFIED / NOT LEGAL ADVICE` until a named human reviews
    it, and that is the loudest "not ready" signal in an audit conversation. The blocker has
    never been the workflow, it has been that nobody could hand a reviewer a reviewable
    artefact. This is that artefact: the control, what implements it, what evidence it
    produces, and the exact clause claimed — one row per decision the reviewer has to make.
    """
    from sqlalchemy import select

    from ..compliance import load_catalog
    from ..models import FrameworkMapping

    catalog = load_catalog()
    known = {f.get("key") if isinstance(f, dict) else f for f in catalog.get("frameworks", [])}
    if framework not in known:
        console.print(f"[red]unknown framework '{framework}'[/] — known: {', '.join(sorted(known))}")
        raise typer.Exit(1)

    controls = {c["key"]: c for c in catalog.get("controls", [])}
    with _session() as session:
        mappings = list(
            session.scalars(
                select(FrameworkMapping).where(FrameworkMapping.framework == framework)
            )
        )
        rows = [
            {
                "control_key": m.control_key,
                "reference": m.reference,
                "status": m.review_status,
                "reviewed_by": m.reviewed_by or "",
            }
            for m in mappings
        ]

    rows.sort(key=lambda r: (r["control_key"], r["reference"]))
    drafts = [r for r in rows if r["status"] != "reviewed"]

    lines = [
        f"# Compliance mapping review packet — {framework}",
        "",
        f"{len(rows)} mapping(s), {len(drafts)} awaiting review.",
        "",
        "For each row: does this control, as implemented, support the clause claimed? Approve with",
        "`agentfox compliance review <control> --framework "
        f"{framework} --reviewer \"<your name>\"`, optionally `--reference` for a single clause.",
        "",
    ]
    for key in sorted({r["control_key"] for r in rows}):
        control = controls.get(key, {})
        objective = " ".join(str(control.get("objective", "")).split())
        lines += [
            f"## {key} — {control.get('title', '')}",
            "",
            f"**Objective.** {objective}" if objective else "",
            f"**Implemented by.** {', '.join(control.get('implemented_by', [])) or 'not recorded'}",
            f"**Evidence produced.** {', '.join(control.get('evidence_sources', [])) or 'not recorded'}",
            "",
            "| Clause claimed | Current status | Reviewed by |",
            "|---|---|---|",
        ]
        for row in [r for r in rows if r["control_key"] == key]:
            lines.append(f"| {row['reference']} | {row['status']} | {row['reviewed_by'] or '—'} |")
        lines.append("")

    document = "\n".join(line for line in lines if line is not None)
    if out:
        out.write_text(document)
        console.print(f"[green]wrote[/] {out}  [dim]{len(rows)} mapping(s), {len(drafts)} draft[/]")
    else:
        console.print(document)


@compliance_app.command("review")
def compliance_review(
    control: str,
    framework: str = typer.Option(..., "--framework"),
    reviewer: str = typer.Option(..., "--reviewer", help="The human accountable for this sign-off."),
    reference: str | None = typer.Option(
        None, "--reference", help="Sign off one clause only; default is every clause for the control."
    ),
) -> None:
    """Record a qualified reviewer's sign-off on a control's framework mapping(s).

    This is an attestation by a named person, recorded and auditable. It is the step that
    moves a mapping from `DRAFT — UNVERIFIED / NOT LEGAL ADVICE` to reviewed, and it should
    be run by whoever is actually accountable for the claim — not by whoever runs the CLI.
    """
    from ..compliance.catalog import review_mapping

    with _session() as session:
        count = review_mapping(session, control, framework, reviewer, reference)

    if not count:
        console.print(
            f"[yellow]no mapping matched[/] {control} / {framework}"
            + (f" / {reference}" if reference else "")
        )
        raise typer.Exit(1)
    console.print(f"[green]{count} mapping(s) reviewed[/] — {control} / {framework}, by {reviewer}")
    console.print("  [dim]recorded as an attestation by that named reviewer[/]")


@compliance_app.command("frameworks")
def compliance_frameworks() -> None:
    """List frameworks, coverage and review status."""
    from ..compliance import all_frameworks

    with _session() as session:
        rows = all_frameworks(session)
    table = Table(box=None, pad_edge=False)
    for column in ("framework", "controls mapped", "mappings", "reviewed", "status"):
        table.add_column(column, style="bold" if column == "framework" else None)
    for row in rows:
        table.add_row(
            row["title"],
            f"{row['controls_mapped']}/{row['controls_total']}",
            str(row["mappings_total"]),
            str(row["mappings_reviewed"]),
            "[green]reviewed[/]" if row["review_status"] == "reviewed" else "[yellow]draft[/]",
        )
    console.print(table)
    console.print(
        "\n[yellow]All mappings are engineering drafts. They are not legal advice and "
        "ship inside evidence packages tagged DRAFT — UNVERIFIED / NOT LEGAL ADVICE "
        "until reviewed.[/]"
    )


@compliance_app.command("risk")
def compliance_risk() -> None:
    """Show the agent risk register (P6-3)."""
    from ..compliance import register

    with _session() as session:
        rows = register(session)
    table = Table(box=None, pad_edge=False)
    for column in ("agent", "risk tier", "EU class", "residual", "assessed", "review"):
        table.add_column(column, style="bold" if column == "agent" else None)
    for row in rows:
        table.add_row(
            row["agent"],
            row["risk_tier"],
            row["eu_ai_act_class"] or "—",
            row["residual_risk"] or "—",
            "[green]yes[/]" if row["assessed"] else "[red]no[/]",
            "[red]overdue[/]" if row["review_overdue"] else (row["next_review_at"] or "—")[:10],
        )
    console.print(table)


@compliance_app.command("obligations")
def compliance_obligations() -> None:
    """Regulatory obligation calendar against the agent inventory (P6-5)."""
    from ..compliance import obligation_calendar

    with _session() as session:
        rows = obligation_calendar(session)
    table = Table(box=None, pad_edge=False)
    for column in ("date", "framework", "obligation", "status", "agents", "build by"):
        table.add_column(column, style="bold" if column == "obligation" else None)
    for row in rows:
        colour = {"live": "green"}.get(row["status"], "yellow")
        table.add_row(
            (row["effective_date"] or "")[:10],
            row["framework"],
            row["title"][:44],
            f"[{colour}]{row['status']}[/]",
            str(row["agents_in_scope_count"]),
            (row["target_readiness"] or "—")[:10],
        )
    console.print(table)


@compliance_app.command("board")
def compliance_board() -> None:
    """Executive risk view (P6-6)."""
    from ..compliance import board_view

    with _session() as session:
        view = board_view(session)
    inventory = view["inventory"]
    console.print(Panel.fit("[bold]AI risk posture[/]", border_style="cyan"))
    console.print(
        f"  agents under management  {inventory['agents']} "
        f"([red]{inventory['shadow']} shadow[/], "
        f"[yellow]{inventory['unowned']} unowned[/])"
    )
    console.print(
        f"  high-risk agents         {len(view['high_risk_agents'])} {view['high_risk_agents']}"
    )
    console.print(
        f"  unassessed agents        {len(view['unassessed_agents'])} {view['unassessed_agents']}"
    )
    findings = view["open_findings"]
    console.print(f"  open findings            {findings['total']} {findings['by_severity']}")
    overall = view["overall_posture"]
    console.print(
        f"  control effectiveness    "
        f"{(overall['effectiveness'] or 0):.0%} of "
        f"{overall['controls']} controls"
    )
    console.print(f"  live obligations         {len(view['live_obligations'])}")
    console.print(f"  upcoming (24mo)          {len(view['upcoming_obligations'])}")
    console.print(f"\n[yellow]{view['caveat']}[/]")


# ---------------------------------------------------------------------------
# redteam / scan
# ---------------------------------------------------------------------------


@redteam_app.command("run")
def redteam_run(
    agent: str,
    probes: str | None = None,
    adaptive: bool = typer.Option(
        False,
        "--adaptive",
        help="Mutate a blocked probe and try again, steering from the failure. Reports a "
        "posture delta against the last comparable campaign, not a pass rate.",
    ),
    budget: int = typer.Option(3, "--budget", help="Attempts per probe in adaptive mode."),
    seed: int = typer.Option(1337, "--seed", help="Fixes the mutation program."),
    deployment_probes: bool = typer.Option(
        True,
        "--deployment-probes/--no-deployment-probes",
        help="Generate probes from this deployment's own grants, impacts and bound policies.",
    ),
) -> None:
    """Run adversarial probes against the deployed configuration (P4-4).

    This measures whether *this configuration* got weaker, against known attack classes.
    It is not a robustness certificate, and `--adaptive` does not make it one: every
    published result says an attacker who adapts eventually gets through.
    """
    from sqlalchemy import select

    from ..evaluation import run_campaign
    from ..models import RedTeamFinding

    keys = [p.strip() for p in probes.split(",")] if probes else None
    with _session() as session:
        campaign = run_campaign(
            session,
            agent,
            probes=keys,
            adaptive=adaptive,
            budget=budget,
            seed=seed,
            include_deployment_probes=deployment_probes,
        )
        stats = campaign.summary_json
        findings = list(
            session.scalars(select(RedTeamFinding).where(RedTeamFinding.campaign_id == campaign.id))
        )
        rows = [
            {
                "probe": f.probe,
                "severity": f.severity,
                "succeeded": f.succeeded,
                "owasp": f.owasp_id,
                "verdict": (f.evidence_json or {}).get("verdict"),
                "expect_blocked": (f.evidence_json or {}).get("expect_blocked", True),
                "over_blocked": (f.evidence_json or {}).get("over_blocked", False),
            }
            for f in findings
        ]

    console.print(
        f"[bold]{agent}[/] — {stats['probes_run']} probes "
        f"({stats.get('attacks_run', stats['probes_run'])} attacks, "
        f"{stats.get('benign_probes_run', 0)} benign controls)"
    )
    console.print(
        f"  recall (attacks caught) [bold]{stats.get('recall', stats['posture_score']):.0%}[/] — "
        f"[green]{stats['attacks_blocked']} blocked[/], "
        f"[red]{stats['attacks_succeeded']} got through[/]"
    )
    if stats.get("benign_probes_run"):
        console.print(
            f"  precision [bold]{stats.get('precision', 1.0):.0%}[/] — "
            f"[red]{stats['benign_false_positives']} legitimate call(s) wrongly blocked[/]"
            if stats["benign_false_positives"]
            else f"  precision [bold]{stats.get('precision', 1.0):.0%}[/] — "
            "[green]no benign controls wrongly blocked[/]"
        )
    # Adaptive mode answers a different question from the static suite, so it leads with
    # a different line: not "what share did we catch" but "did this deployment get weaker".
    if stats.get("headline"):
        console.print(f"\n  [bold]{stats['headline']}[/]")
    posture = stats.get("posture") or {}
    if posture.get("direction") and posture["direction"] != "no_baseline":
        colour = {"weaker": "red", "stronger": "green"}.get(posture["direction"], "dim")
        console.print(
            f"  posture [{colour}]{posture['direction']}[/] vs. the last comparable campaign — "
            f"{len(posture.get('new_escapes') or [])} new escape(s), "
            f"{len(posture.get('resolved_escapes') or [])} resolved"
        )
    elif adaptive and not stats.get("headline"):
        console.print("  [dim]no comparable baseline yet — this campaign becomes it[/]")
    adaptive_stats = stats.get("adaptive") or {}
    by_class = adaptive_stats.get("escape_rate_by_semantics") or {}
    if by_class:
        console.print(
            "  escapes by payload kind: "
            + "  ".join(f"{name} {value}" for name, value in sorted(by_class.items()))
        )
    if adaptive_stats.get("observe_mode_policies"):
        console.print(
            "  [yellow]note[/] — "
            f"{', '.join(adaptive_stats['observe_mode_policies'])} bound in observe mode; "
            "probes score the counterfactual verdict, so this campaign cannot see that."
        )

    table = Table(box=None, pad_edge=False)
    for column in ("probe", "severity", "OWASP", "verdict", "result"):
        table.add_column(column, style="bold" if column == "probe" else None)
    for row in rows:
        if row["over_blocked"]:
            result = "[red]OVER-BLOCKED (false positive)[/]"
        elif row["expect_blocked"] and row["succeeded"]:
            result = "[red]NOT BLOCKED (attack succeeded)[/]"
        elif row["expect_blocked"]:
            result = "[green]blocked[/]"
        else:
            result = "[green]allowed[/]"
        table.add_row(row["probe"], row["severity"], row["owasp"] or "—", row["verdict"] or "—", result)
    console.print(table)


@redteam_app.command("probes")
def redteam_probes() -> None:
    """List the built-in probe suite and available wrapped runners."""
    from ..evaluation.redteam import BUILTIN_PROBES, available_runners

    table = Table(box=None, pad_edge=False)
    for column in ("probe", "category", "surface", "severity", "OWASP", "ATLAS"):
        table.add_column(column, style="bold" if column == "probe" else None)
    for probe in BUILTIN_PROBES:
        table.add_row(
            probe.key,
            probe.category,
            probe.surface,
            probe.severity,
            probe.owasp_id or "—",
            probe.atlas_id or "—",
        )
    console.print(table)
    runners = available_runners()
    console.print(
        "\n  wrapped runners: "
        + "  ".join(
            f"[{'green' if ok else 'dim'}]{name}{'' if ok else ' (not installed)'}[/]"
            for name, ok in runners.items()
        )
    )


@scan_app.command("mcp")
def scan_mcp(
    server: str,
    file: Path | None = typer.Option(
        None, "--file", help="Tool list JSON (what the server's tools/list returned)."
    ),
    seed_fixture: bool = typer.Option(
        False,
        "--seed-fixture",
        help="Scan the built-in demo tool list instead of --file. For demos only.",
    ),
) -> None:
    """Snapshot an MCP server's tools and check hygiene (P1-5)."""
    from sqlalchemy import select

    from ..models import McpServer
    from ..registry.service import scan_mcp_server
    from ..seed import MCP_TOOLS

    if file is None and not seed_fixture:
        # Silently scanning the seed fixture reported a clean (or dirty) bill of health
        # for tools that server never declared.
        console.print(
            "[red]--file is required[/] — pass the server's tool list as JSON. "
            "[dim](--seed-fixture scans the built-in demo tool list instead.)[/]"
        )
        raise typer.Exit(2)
    if file is not None and seed_fixture:
        console.print("[red]pass either --file or --seed-fixture, not both[/]")
        raise typer.Exit(2)

    tools = json.loads(file.read_text()) if file else MCP_TOOLS
    with _session() as session:
        record = session.scalar(select(McpServer).where(McpServer.name == server))
        if record is None:
            console.print(f"[red]unknown MCP server '{server}'[/]")
            raise typer.Exit(1)
        result = scan_mcp_server(session, record, tools)

    console.print(f"[bold]{server}[/] — {result['tools']} tools, digest {result['digest'][:16]}…")
    if not result["issues"]:
        console.print("  [green]no hygiene issues[/]")
    for issue in result["issues"]:
        colour = SEVERITY_COLOUR.get(issue["severity"], "dim")
        console.print(
            f"  [{colour}]{issue['severity']}[/] {issue['type']}"
            + (f" — {issue.get('tool')}" if issue.get("tool") else "")
        )
        if issue.get("excerpt"):
            console.print(f"      [dim]{issue['excerpt'][:120]}[/]")
    external = result["external_scan"]
    if not external["ran"]:
        console.print(f"  [dim]mcp-scan: {external['reason']}[/]")


@app.command()
def analyse_action(
    statement: str = typer.Argument(..., help="SQL, shell command or URL to analyse"),
    kind: str = typer.Option("sql", help="sql | shell | http"),
    method: str = typer.Option("GET", help="HTTP method, when kind=http"),
    dialect: str = typer.Option("postgres", help="SQL dialect"),
    environment: str = typer.Option("production", help="environment the action binds to"),
) -> None:
    """Read an artefact and say what running it would actually do (P9).

    Deterministic, offline and immediate: no database, no model, no network. The point
    is that an engineer can check a generated statement before it is ever executed.
    """
    from ..guardrails.actions import analyse_http, analyse_shell, analyse_sql, summarise

    if kind == "shell":
        analysis = analyse_shell(statement)
    elif kind == "http":
        analysis = analyse_http(method, statement)
    else:
        analysis = analyse_sql(statement, dialect=dialect)

    summary = summarise([analysis], environment)
    colour = SEVERITY_COLOUR.get(analysis.severity, "green")
    console.print(
        f"[bold]{analysis.operation}[/] · blast radius [{colour}]{analysis.blast_radius}[/] · "
        f"{'reversible' if analysis.reversible else 'IRREVERSIBLE'} · "
        f"{len(analysis.targets)} target(s): {', '.join(analysis.targets) or '—'}"
    )
    if not summary.get("risks"):
        console.print("  [green]no risks identified[/]")
    for risk in summary.get("risks", []):
        risk_colour = SEVERITY_COLOUR.get(risk["severity"], "dim")
        console.print(f"  [{risk_colour}]{risk['severity']}[/] {risk['code']} — {risk['detail']}")
    if summary.get("critical"):
        raise typer.Exit(1)


@tools_app.command("declare")
def tools_declare(
    key: str,
    impact: str = typer.Option(
        ...,
        "--impact",
        help="read | write | high_impact | irreversible — the axis every containment rule reasons over.",
    ),
    name: str = typer.Option("", "--name"),
    description: str = typer.Option("", "--description"),
    triggers: str = typer.Option("", "--triggers", help="Comma-separated downstream effects."),
) -> None:
    """Declare a tool and what it can do (P9).

    Containment is declared, not detected: an irreversible tool recorded as `read` is one
    a tainted argument can reach. This is the command that makes least privilege real, and
    it is deliberately the first thing `agentfox init` points at.
    """
    from ..registry.service import upsert_tool

    valid = ("read", "write", "high_impact", "irreversible")
    if impact not in valid:
        console.print(f"[red]impact must be one of: {', '.join(valid)}[/]")
        raise typer.Exit(2)

    with _session() as session:
        tool = upsert_tool(
            session,
            key,
            name=name,
            impact=impact,
            description=description,
        )
        if triggers:
            tool.triggers_json = [t.strip() for t in triggers.split(",") if t.strip()]
        declared_triggers = list(tool.triggers_json or [])

    console.print(f"[bold]{key}[/] declared — impact [bold]{impact}[/]")
    if declared_triggers:
        console.print(f"  triggers: {', '.join(declared_triggers)}")
    if impact in ("high_impact", "irreversible"):
        console.print(
            "  [dim]arguments carrying untrusted provenance now require approval or are "
            "refused, whether or not a detector fires[/]"
        )


@tools_app.command("list")
def tools_list(as_json: bool = typer.Option(False, "--json")) -> None:
    """Every declared tool and what it is allowed to do."""
    from sqlalchemy import select

    from ..models import Tool

    with _session() as session:
        tools = list(session.scalars(select(Tool).order_by(Tool.key)))
        rows = [
            {
                "key": t.key,
                "impact": t.impact,
                "triggers": list(t.triggers_json or []),
                "description": t.description,
            }
            for t in tools
        ]

    if as_json:
        _emit(rows, True)
        return
    if not rows:
        console.print("[yellow]no tools declared[/] — `agentfox tools declare <key> --impact ...`")
        return
    table = Table(box=None, padding=(0, 2))
    table.add_column("tool")
    table.add_column("impact")
    table.add_column("triggers")
    for row in rows:
        colour = {"irreversible": "red", "high_impact": "yellow", "write": "cyan"}.get(
            row["impact"], "dim"
        )
        table.add_row(row["key"], f"[{colour}]{row['impact']}[/]", ", ".join(row["triggers"]) or "—")
    console.print(table)


@tools_app.command("set-triggers")
def tools_set_triggers(
    key: str = typer.Argument(..., help="Tool key, e.g. demo.delete_user"),
    triggers: str = typer.Option(
        "", "--triggers", help="Comma-separated tool keys this call sets off downstream"
    ),
) -> None:
    """P9 — declare what a tool call sets off downstream (a DB trigger, a webhook, a
    fan-out), so `cascade_risk()` can actually see it. An undeclared trigger stays
    invisible by design (see `effects.cascade_risk`'s own docstring) — this is how
    an operator closes that gap for one tool.
    """
    from sqlalchemy import select

    from ..models import Tool

    declared = [t.strip() for t in triggers.split(",") if t.strip()]
    with _session() as session:
        tool = session.scalar(select(Tool).where(Tool.key == key))
        if tool is None:
            console.print(
                f"[red]unknown tool '{key}' — register it first "
                "(agentfox scan mcp, or via seed data)[/]"
            )
            raise typer.Exit(1)
        tool.triggers_json = declared

    console.print(f"[bold]{key}[/] triggers: {', '.join(declared) or '(none)'}")


@access_app.command("declare-scope")
def access_declare_scope(
    table: str = typer.Argument(..., help="Table name"),
    column: str = typer.Option(
        ..., "--column", help="Column that decides whose row it is"
    ),
    principal_key: str = typer.Option(
        "id",
        "--principal-key",
        help="Attribute of the calling principal the column must equal",
    ),
    restricted_columns: str = typer.Option(
        "",
        "--restricted-columns",
        help="Comma-separated columns nobody should receive even for their own row",
    ),
) -> None:
    """P18 — declare which column on a table decides whose row it is, so
    `analyse_access()` can prove a query is scoped instead of assuming it. An
    undeclared table is reported, never assumed safe (see `data_access`'s own
    docstring).
    """
    from sqlalchemy import select

    from ..models import AccessScopeRule

    restricted = [c.strip() for c in restricted_columns.split(",") if c.strip()]
    with _session() as session:
        rule = session.scalar(
            select(AccessScopeRule).where(AccessScopeRule.table_name == table)
        )
        if rule is None:
            rule = AccessScopeRule(table_name=table)
            session.add(rule)
        rule.is_reference = False
        rule.column = column
        rule.principal_key = principal_key
        rule.restricted_columns = restricted

    suffix = f" (restricted: {', '.join(restricted)})" if restricted else ""
    console.print(f"[bold]{table}[/] scoped by {column} = principal.{principal_key}{suffix}")


@access_app.command("declare-reference")
def access_declare_reference(
    table: str = typer.Argument(
        ..., help="Table name — belongs to nobody (currencies, statuses, postcodes)"
    ),
) -> None:
    """P18 — declare a table that belongs to nobody, so `analyse_access()` does not
    flag it as an undeclared/unscoped table.
    """
    from sqlalchemy import select

    from ..models import AccessScopeRule

    with _session() as session:
        rule = session.scalar(
            select(AccessScopeRule).where(AccessScopeRule.table_name == table)
        )
        if rule is None:
            rule = AccessScopeRule(table_name=table, is_reference=True)
            session.add(rule)
        else:
            rule.is_reference = True

    console.print(f"[bold]{table}[/] declared as a reference table")


# ---------------------------------------------------------------------------
# proposals — the governed improvement loop's inbox
# ---------------------------------------------------------------------------

proposals_app = typer.Typer(
    help="Proposed changes to governance configuration: review, decide, apply, undo.",
    no_args_is_help=True,
)
app.add_typer(proposals_app, name="proposals")


def _load_proposal(session, proposal_id: str):
    from ..improvement.proposals import get_proposal

    proposal = get_proposal(session, proposal_id)
    if proposal is None:
        console.print(f"[red]unknown proposal '{proposal_id}'[/]")
        raise typer.Exit(1)
    return proposal


def _proposal_step(proposal_id: str, step) -> None:
    """Run one lifecycle step; a refused step exits non-zero and changes nothing."""
    from ..improvement.proposals import proposal_json

    with _session() as session:
        proposal = _load_proposal(session, proposal_id)
        try:
            step(session, proposal)
        except ValueError as exc:
            console.print(f"[red]refused:[/] {exc}")
            raise typer.Exit(1) from exc
        body = proposal_json(proposal)
    note = " (awaiting a second approver)" if body["awaiting_second_approver"] else ""
    console.print(f"[bold]{body['id']}[/] → [bold]{body['status']}[/]{note}")


@proposals_app.command("list")
def proposals_list(
    status: str | None = typer.Option(None, help="Filter by lifecycle status"),
    kind: str | None = typer.Option(None, help="Filter by change kind"),
    scope_level: str | None = typer.Option(None, "--scope", help="org | team | agent | user"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """List proposals, newest first."""
    from ..improvement.proposals import list_proposals, proposal_json

    with _session() as session:
        rows = [
            proposal_json(p)
            for p in list_proposals(session, status=status, kind=kind, scope_level=scope_level)
        ]
    if as_json:
        _emit({"proposals": rows}, True)
        return
    if not rows:
        # The only list command in the CLI that printed a bare header row and
        # stopped. Every other one says what is missing and how to get some.
        filtered = any((status, kind, scope_level))
        console.print(
            "[dim]no proposals match that filter[/]"
            if filtered
            else "[dim]no proposals — `agentfox proposals from-labels` files them from "
            "false positives you have labelled.[/]"
        )
        return
    table = Table(box=None, pad_edge=False)
    for column in ("id", "status", "kind", "direction", "autonomy", "scope", "title"):
        table.add_column(column, style="bold" if column == "id" else None)
    for row in rows:
        colour = "red" if row["direction"] == "loosens" else "green"
        table.add_row(
            row["id"],
            row["status"],
            row["kind"],
            f"[{colour}]{row['direction']}[/]",
            row["autonomy_level"],
            f"{row['scope_level']}:{row['scope_id']}",
            row["title"][:60],
        )
    console.print(table)


@proposals_app.command("show")
def proposals_show(proposal_id: str, as_json: bool = typer.Option(False, "--json")) -> None:
    """Show one proposal: its diff, evidence, proof and decisions."""
    from ..improvement.proposals import proposal_json

    with _session() as session:
        body = proposal_json(_load_proposal(session, proposal_id))
    if as_json:
        _emit(body, True)
        return
    console.print(
        Panel.fit(
            f"[bold]{body['title']}[/]\n"
            f"status     {body['status']}\n"
            f"kind       {body['kind']} ({body['direction']}, {body['autonomy_level']})\n"
            f"scope      {body['scope_level']}:{body['scope_id']}\n"
            f"target     {body['target_type']}:{body['target_ref']}\n"
            f"proposed   {body['proposed_by']}\n"
            f"decided    {body['decided_by'] or '-'}"
            f"{' + ' + body['second_approver'] if body['second_approver'] else ''}\n"
            f"rationale  {body['rationale']}",
            border_style="cyan",
        )
    )
    console.print_json(json.dumps({"diff": body["diff"], "proof": body["proof"]}, default=str))


@proposals_app.command("approve")
def proposals_approve(
    proposal_id: str,
    actor: str = typer.Option(..., "--actor", help="Your name or email — decisions are named"),
    note: str = typer.Option(..., "--note", help="Why"),
) -> None:
    """Approve a proven proposal. An org-level loosening needs two different people."""
    from ..improvement.proposals import decide

    _proposal_step(
        proposal_id, lambda s, p: decide(s, p, approve=True, actor=actor, note=note)
    )


@proposals_app.command("reject")
def proposals_reject(
    proposal_id: str,
    actor: str = typer.Option(..., "--actor", help="Your name or email — decisions are named"),
    note: str = typer.Option(..., "--note", help="Why"),
) -> None:
    """Reject a proposal."""
    from ..improvement.proposals import decide

    _proposal_step(
        proposal_id, lambda s, p: decide(s, p, approve=False, actor=actor, note=note)
    )


@proposals_app.command("apply")
def proposals_apply(
    proposal_id: str,
    actor: str | None = typer.Option(None, "--actor", help="Your name or email"),
    automated: bool = typer.Option(
        False,
        "--automated",
        help="Apply as the improvement loop, subject to autonomy, freeze and daily cap",
    ),
) -> None:
    """Apply an approved proposal (or settle one whose canary has finished)."""
    from ..improvement.proposals import apply_proposal

    if not automated and not actor:
        console.print("[red]--actor is required unless --automated[/]")
        raise typer.Exit(1)
    _proposal_step(
        proposal_id,
        lambda s, p: apply_proposal(s, p, actor=actor, automated=automated),
    )


@proposals_app.command("rollback")
def proposals_rollback(
    proposal_id: str,
    actor: str = typer.Option(..., "--actor", help="Your name or email"),
    reason: str = typer.Option(..., "--reason", help="Why it is being undone"),
) -> None:
    """Undo an applied or canaried proposal."""
    from ..improvement.proposals import rollback_proposal

    _proposal_step(
        proposal_id,
        lambda s, p: rollback_proposal(s, p, reason=reason, actor=actor),
    )



@proposals_app.command("verify")
def proposals_verify(
    proposal_id: str,
    actor: str = typer.Option(..., "--actor", help="Your name or email"),
    note: str = typer.Option(..., "--note", help="What the evidence showed"),
    failed: bool = typer.Option(
        False, "--failed", help="The change did not do what it promised: record it and roll back."
    ),
) -> None:
    """Close the loop on an applied change: did it do what it promised?

    `--failed` rolls the change back. If undoing it would loosen a control, it stays
    applied with the failure recorded, because that rollback is a person's decision.
    """
    from ..improvement.proposals import verify_proposal

    _proposal_step(
        proposal_id,
        lambda s, p: verify_proposal(s, p, verified=not failed, note=note, actor=actor),
    )


@proposals_app.command("from-labels")
def proposals_from_labels(
    days: int = typer.Option(30, help="Label window in days"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """File rule cut-off proposals from labelled false positives. Nothing is applied."""
    from ..improvement.loops import propose_threshold_changes

    with _session() as session:
        report = propose_threshold_changes(session, days=days).to_json()
    if as_json:
        _emit(report, True)
        return
    console.print(
        f"filed {len(report['filed'])}, refreshed {len(report['refreshed'])}, "
        f"superseded {len(report['superseded'])}"
    )
    for skip in report["skipped"]:
        where = "/".join(str(skip[k]) for k in ("detector_key", "policy", "rule_id") if k in skip)
        console.print(f"  [dim]skipped {where}: {skip['reason']}[/]")

def main() -> None:  # pragma: no cover - console entry point
    try:
        app()
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":  # pragma: no cover
    main()
