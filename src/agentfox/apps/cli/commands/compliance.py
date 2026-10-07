"""Where this deployment stands against each framework (`agentfox report …`, `admin catalog …`)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import typer
from rich.panel import Panel
from rich.table import Table

from agentfox.apps.cli.commands._shared import _session, console

compliance_app = typer.Typer(
    help="Where this deployment stands against each framework, computed from telemetry.",
    no_args_is_help=True,
)


@compliance_app.command("sync")
def compliance_sync() -> None:
    """Load the control catalog and obligation calendar from YAML."""
    from agentfox.capabilities.compliance.catalog import sync_catalog, sync_obligations

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
    """Recompute control status from telemetry."""
    from agentfox.capabilities.compliance import compute_all, posture

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

    from agentfox.capabilities.compliance import (
        controls_for_framework,
        framework_coverage,
        latest_statuses,
        posture,
    )
    from agentfox.core.models import Control

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

    Read-only and offline: parses the compliance packs' controls.yaml and
    obligations.yaml (or those under `compliance_dir`, when it is set) and never
    touches the database. Exits 1 on any
    problem, so it can gate a catalog change the way `policy lint` gates a policy.
    """
    import yaml

    from agentfox.capabilities.compliance.catalog import (
        catalog_path,
        catalog_paths,
        merge_catalogs,
        obligations_paths,
    )
    from agentfox.capabilities.compliance.status import RULE_KINDS

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

    catalog_files = catalog_paths() or [catalog_path()]
    catalog = merge_catalogs([_load(path) for path in catalog_files])
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

    obligations = [
        spec
        for path in obligations_paths() or [Path("obligations.yaml")]
        for spec in _load(path).get("obligations") or []
    ]
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
        f"[bold]control catalog[/] v{catalog.get('version', '?')}  "
        f"[dim]{', '.join(str(path) for path in catalog_files)}[/]"
    )
    console.print(f"  controls     {len(controls)}")
    console.print(f"  frameworks   {len(known)}")
    console.print(
        f"  mappings     {mappings}  ([yellow]{mappings - reviewed} draft[/], {reviewed} reviewed)"
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
    """Everything a qualified reviewer needs to sign off one framework, in one file.

    Every mapping ships `DRAFT — UNVERIFIED / NOT LEGAL ADVICE` until a named human reviews
    it, and that is the loudest "not ready" signal in an audit conversation. The blocker has
    never been the workflow, it has been that nobody could hand a reviewer a reviewable
    artefact. This is that artefact: the control, what implements it, what evidence it
    produces, and the exact clause claimed — one row per decision the reviewer has to make.
    """
    from sqlalchemy import select

    from agentfox.capabilities.compliance import load_catalog
    from agentfox.core.models import FrameworkMapping

    catalog = load_catalog()
    known = {f.get("key") if isinstance(f, dict) else f for f in catalog.get("frameworks", [])}
    if framework not in known:
        console.print(
            f"[red]unknown framework '{framework}'[/] — known: {', '.join(sorted(known))}"
        )
        raise typer.Exit(1)

    controls = {c["key"]: c for c in catalog.get("controls", [])}
    with _session() as session:
        mappings = list(
            session.scalars(select(FrameworkMapping).where(FrameworkMapping.framework == framework))
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
        "`agentfox report signoff <control> --framework "
        f'{framework} --reviewer "<your name>"`, optionally `--reference` for a single clause.',
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
            (
                "**Evidence produced.** "
                f"{', '.join(control.get('evidence_sources', [])) or 'not recorded'}"
            ),
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
    reviewer: str = typer.Option(
        ..., "--reviewer", help="The human accountable for this sign-off."
    ),
    reference: str | None = typer.Option(
        None,
        "--reference",
        help="Sign off one clause only; default is every clause for the control.",
    ),
) -> None:
    """Record a qualified reviewer's sign-off on a control's framework mapping(s).

    This is an attestation by a named person, recorded and auditable. It is the step that
    moves a mapping from `DRAFT — UNVERIFIED / NOT LEGAL ADVICE` to reviewed, and it should
    be run by whoever is actually accountable for the claim — not by whoever runs the CLI.
    """
    from agentfox.capabilities.compliance.catalog import sign_off_mapping

    with _session() as session:
        count = sign_off_mapping(session, control, framework, reviewer, reference)

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
    from agentfox.capabilities.compliance import all_frameworks

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
    """Show the agent risk register."""
    from agentfox.capabilities.compliance import register

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
    """Regulatory obligation calendar against the agent inventory."""
    from agentfox.capabilities.compliance import obligation_calendar

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
    """Executive risk view."""
    from agentfox.capabilities.compliance import board_view

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
    counts = overall["counts"]
    assessed = sum(counts.get(k, 0) for k in ("effective", "degraded", "failing"))
    # Counts, not the ratio alone: "100%" over 5 assessed controls of 43 read as
    # full coverage on a deployment with almost no evidence yet.
    console.print(
        f"  controls with evidence   {counts.get('effective', 0)} of {overall['controls']} "
        f"effective [dim]({assessed} assessed, "
        f"{counts.get('not_implemented', 0) + counts.get('not_computed', 0)} with no "
        "evidence yet)[/]"
    )
    console.print(f"  live obligations         {len(view['live_obligations'])}")
    console.print(f"  upcoming (24mo)          {len(view['upcoming_obligations'])}")
    console.print(f"\n[yellow]{view['caveat']}[/]")
