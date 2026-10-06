"""`agentfox policy` — write the rules, simulate them on recorded traffic, turn them on."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import typer
from rich.table import Table

from agentfox.cli._style import SEVERITY_COLOUR
from agentfox.cli.commands._shared import _session, console

policy_app = typer.Typer(
    help="Write the rules, try them against recorded traffic, then turn them on.",
    no_args_is_help=True,
)


@policy_app.command("packs")
def policy_packs() -> None:
    """Policy packs on disk, and where each came from.

    `policy list` reads the database: what is installed and what mode it is in.
    This reads the filesystem and answers the question an operator has about a
    policy they did not write — which file is this, and did something override
    it. A project pack replacing a shipped one is invisible in `policy list`,
    because by then they are the same row.
    """
    from agentfox.policy import PolicyPackError, pack_sources, project_policy_dir

    try:
        rows = pack_sources()
    except PolicyPackError as exc:
        console.print(f"[red]a policy pack could not be read[/]\n  {exc}")
        raise typer.Exit(1) from exc
    if not rows:
        console.print("[dim]no policy packs found — this is a broken install.[/]")
        raise typer.Exit(1)

    table = Table(box=None, pad_edge=False)
    for column in ("pack", "origin", "mode", "rules", "file"):
        table.add_column(column, style="bold" if column == "pack" else None)
    for row in rows:
        origin = row["origin"]
        table.add_row(
            row["key"],
            f"[cyan]{origin}[/]" if origin == "project" else f"[dim]{origin}[/]",
            row["mode"],
            row["rules"],
            f"[dim]{row['path']}[/]",
        )
    console.print(table)

    overrides = [r for r in rows if r["overrides"]]
    for row in overrides:
        console.print(
            f"  [yellow]{row['key']}[/] replaces the shipped pack at [dim]{row['overrides']}[/]"
        )

    project = project_policy_dir()
    if not project.exists():
        console.print(
            f"\n[dim]Put your own packs in {PROJECT_DIR_HINT} and they travel with the "
            "repository — `agentfox init` installs them alongside the shipped ones.[/]"
        )


#: Written out rather than interpolated from `project_policy_dir()`, which is
#: absolute: the hint is about what to create, and an absolute path from
#: whatever directory the operator happened to be in reads as a demand.
PROJECT_DIR_HINT = ".agentfox/policies/"


@policy_app.command("list")
def policy_list() -> None:
    """List policies and their enforcement mode."""
    from sqlalchemy import select

    from agentfox.core.models import Policy, PolicyVersion
    from agentfox.policy import current_binding

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
            # The live binding, whichever version it points at — mid-canary or after
            # a rollback that is not the newest version (#65).
            binding, bound = current_binding(session, policy.id)
            mode = binding.mode if binding else "unbound"
            shown = bound or latest
            version = f"v{shown.version}"
            if bound is not None and bound.id != latest.id:
                version += f" [dim](v{latest.version} saved, not live)[/]"
            table.add_row(
                policy.key,
                version,
                f"[green]{mode}[/]" if mode == "enforce" else f"[yellow]{mode}[/]",
                str(len((shown.compiled_json or {}).get("rules", []))),
            )
        console.print(table)


@policy_app.command("lint")
def policy_lint(
    files: list[Path] | None = typer.Argument(
        None,
        help="Policy files to lint, as org-level layers in the order given. "
        "Without files, lints every bound policy layer.",
    ),
) -> None:
    """Lint the policy hierarchy, or policy files. Exits 1 on critical or high findings.

    This is the half of hierarchical policy that produces the 87% misconfiguration
    reduction — composition without a linter just moves the confusion somewhere
    harder to see. Pass files to check them before they are loaded, e.g. in CI.
    """
    from agentfox.policy import lint_all, lint_documents, lint_summary

    if files:
        report = lint_summary(lint_documents([_read_policy_file(path) for path in files]))
    else:
        with _session() as session:
            report = lint_all(session)
    _print_lint(report)
    if not report["passed"]:
        console.print("\n[bold red]LINT FAIL[/] — critical/high findings block the build")
        raise typer.Exit(1)
    if report["findings"]:
        console.print("\n[green]LINT PASS[/] [dim](advisory findings only)[/]")


def _read_policy_file(path: Path):
    from agentfox.policy import PolicyDocument

    try:
        return PolicyDocument.from_yaml(path.read_text())
    except Exception as exc:
        console.print(f"[red]invalid:[/] {path}: {' '.join(str(exc).split())}")
        raise typer.Exit(1) from exc


def _print_lint(report: dict) -> None:
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


@policy_app.command("effective")
def policy_effective(
    agent: str | None = None,
    team: str | None = None,
    user: str | None = None,
    environment: str | None = typer.Option(
        None,
        "--environment",
        help="Environment to resolve for. Defaults to the configured environment "
        "(AGENTFOX_ENVIRONMENT), which is what the runtime itself uses.",
    ),
) -> None:
    """Show the policy actually in force for a subject, and where each rule came from.

    Opacity is what makes layered policy dangerous, so the resolver explains itself.
    """
    from agentfox.core.config import get_settings
    from agentfox.policy import effective_for

    environment = environment or get_settings().environment
    with _session() as session:
        effective = effective_for(
            session, agent_slug=agent, environment=environment, team=team, user=user
        )
        explanation = effective.explain()

    # Per layer, not one mode for the lot: "mode enforce" whenever any layer
    # enforced read as though every rule listed was enforcing (#49).
    console.print(
        f"[bold]effective policy[/] in [bold]{environment}[/] — "
        f"default {explanation['default_effect']}"
    )
    if explanation["layer_modes"]:
        console.print("  [dim]layers:[/]")
        for layer in explanation["layer_modes"]:
            colour = "green" if layer["mode"] == "enforce" else "yellow"
            console.print(
                f"    {layer['level']}:{layer['scope']}({layer['compose']})  "
                f"{layer['policy']}  [{colour}]{layer['mode']}[/]"
            )
        console.print()
    else:
        console.print("  [dim]layers: none[/]\n")

    table = Table(box=None, pad_edge=False)
    for column in ("rule", "effect", "mode", "from", "overrides"):
        table.add_column(column, style="bold" if column == "rule" else None)
    for rule in explanation["rules"]:
        table.add_row(
            rule["rule_id"],
            rule["effect"],
            rule["enforcement"],
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
    """Replay recorded traffic against a candidate policy.

    Exits non-zero when the change would newly block production traffic, so it can
    gate a policy PR the same way `eval gate` gates a code PR.
    """
    from agentfox.policy import PolicyDocument, record_simulation, simulate

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
    for label, colour, records in (
        ("would block", "red", diff.newly_blocked),
        ("would escalate", "yellow", diff.newly_escalated),
        ("would allow", "green", diff.newly_allowed),
    ):
        for record in records[:10]:
            why = (record["reasons"] or [""])[0] or (
                f"was {record['was']}; no longer fires: "
                + (", ".join(record.get("no_longer_fires") or []) or "—")
            )
            console.print(
                f"    [{colour}]{label}[/] {record['agent'] or '—'} {record['surface']} "
                f"{record['tool'] or ''} — {why[:80]}"
            )
        if len(records) > 10:
            console.print(f"    [dim]… and {len(records) - 10} more {label}[/]")
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

    from agentfox.core.models import Policy
    from agentfox.policy import set_mode
    from agentfox.prove.audit import chain

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
    """Check, lint and compile a policy file without saving it.

    Runs the full lint (`policy lint FILE`), so a rule that can never fire or a
    condition naming an unknown value (`surface: [toolargs]`) fails validation.
    Exits 1 on a parse error or a critical/high finding.
    """
    from agentfox.policy import compile_to_rego, lint_documents, lint_summary

    doc = _read_policy_file(file)
    report = lint_summary(lint_documents([doc]))
    if not report["passed"]:
        console.print(f"[red]invalid:[/] {doc.key} — {len(report['blocking'])} blocking finding(s)")
        _print_lint(report)
        raise typer.Exit(1)
    console.print(
        f"[green]valid[/] — {doc.key} v{doc.version}, {len(doc.rules)} rules, mode={doc.mode}"
    )
    console.print(f"  controls: {sorted({c for r in doc.rules for c in r.controls})}")
    console.print(f"  [dim]compiles to {len(compile_to_rego(doc).splitlines())} lines of Rego[/]")
    if report["findings"]:
        _print_lint(report)
