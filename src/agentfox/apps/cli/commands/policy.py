"""`agentfox policy` — write the rules, simulate them on recorded traffic, turn them on."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import typer
from rich.table import Table

from agentfox.apps.cli._style import SEVERITY_COLOUR
from agentfox.apps.cli.commands._shared import _session, console
from agentfox.apps.cli.commands.packs import packs_app

policy_app = typer.Typer(
    help="Write the rules, try them against recorded traffic, then turn them on.",
    no_args_is_help=True,
)
policy_app.add_typer(packs_app, name="packs")


@policy_app.command("list")
def policy_list() -> None:
    """List policies and their enforcement mode."""
    from sqlalchemy import select

    from agentfox.core.models import Policy, PolicyVersion
    from agentfox.platform.policy import current_binding

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
            # a rollback that is not the newest version.
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
    from agentfox.platform.policy import lint_all, lint_documents, lint_summary

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
    from agentfox.platform.policy import PolicyDocument

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
    from agentfox.platform.policy import effective_for

    environment = environment or get_settings().environment
    with _session() as session:
        effective = effective_for(
            session, agent_slug=agent, environment=environment, team=team, user=user
        )
        explanation = effective.explain()

    # Per layer, not one mode for the lot: "mode enforce" whenever any layer
    # enforced read as though every rule listed was enforcing.
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

    if explanation.get("unloadable_policies"):
        console.print("\n[bold red]bound but unloadable — not in force[/]")
        for entry in explanation["unloadable_policies"]:
            console.print(f"  [red]{entry['key']} v{entry['version']}[/] — {entry['error'][:88]}")


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
    from agentfox.platform.policy import PolicyDocument, record_simulation, simulate

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
    from agentfox.platform.ledger import chain
    from agentfox.platform.policy import set_mode

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
    from agentfox.platform.policy import compile_to_rego, lint_documents, lint_summary

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


@policy_app.command("export")
def policy_export(
    out: Path = typer.Option(None, "--out", "-o", help="Write to this file instead of stdout."),
) -> None:
    """Write every policy, custom rule and detector switch as one YAML file."""
    from agentfox.capabilities import workspace

    with _session() as session:
        text = workspace.dump(workspace.export_bundle(session))
    if out is None:
        typer.echo(text, nl=False)
        return
    out.write_text(text)
    console.print(f"[green]wrote[/] {out}")


@policy_app.command("apply")
def policy_apply(
    file: Path,
    yes: bool = typer.Option(False, "--yes", "-y", help="Apply without asking."),
) -> None:
    """Make the workspace match a file from `policy export`. Shows the plan first.

    Anything the file leaves out is left alone. A policy the file moves to enforce
    is simulated against the last week first.
    """
    from agentfox.capabilities import workspace

    try:
        bundle = workspace.parse(file.read_text())
    except (OSError, workspace.BundleError) as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc
    with _session() as session:
        the_plan = workspace.plan(session, bundle)
        changes = the_plan.changes
        if not changes:
            console.print("[green]Nothing to change.[/]")
            return
        table = Table(box=None, pad_edge=False)
        for column in ("", "kind", "key", "detail"):
            table.add_column(column)
        mark = {"new": "[green]+[/]", "changed": "[yellow]~[/]", "mode": "[yellow]~[/]"}
        for item in changes:
            table.add_row(mark[item.change], item.kind.replace("_", " "), item.key, item.detail)
        console.print(table)
        if not yes and not typer.confirm(f"Apply {len(changes)} change(s)?"):
            raise typer.Exit(1)
        applied = workspace.apply(session, bundle, actor="cli", reason=f"applied {file.name}")
        for key, sim in applied.simulations.items():
            counts = sim.get("counts", {})
            console.print(
                f"[bold]{key}[/] enforcing: {counts.get('newly_blocked', 0)} newly blocked "
                f"in {sim.get('replayed', 0)} replayed requests"
            )
    console.print(f"[green]Applied {len(changes)} change(s).[/]")
