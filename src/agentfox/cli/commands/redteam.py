"""`agentfox redteam` — attack your own configuration and score what got through."""

from __future__ import annotations

import typer
from rich.table import Table

from agentfox.cli.commands._shared import _session, console

redteam_app = typer.Typer(
    help="Attack your own configuration and score what got through.",
    no_args_is_help=True,
)


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
    """Run adversarial probes against the deployed configuration.

    This measures whether *this configuration* got weaker, against known attack classes.
    It is not a robustness certificate, and `--adaptive` does not make it one: every
    published result says an attacker who adapts eventually gets through.
    """
    from sqlalchemy import select

    from agentfox.core.models import RedTeamFinding
    from agentfox.evaluation import run_campaign

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
        table.add_row(
            row["probe"], row["severity"], row["owasp"] or "—", row["verdict"] or "—", result
        )
    console.print(table)


@redteam_app.command("probes")
def redteam_probes() -> None:
    """List the built-in probe suite and available wrapped runners."""
    from agentfox.evaluation.redteam import BUILTIN_PROBES, available_runners

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
