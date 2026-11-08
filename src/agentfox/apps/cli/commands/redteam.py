"""Attack your own configuration and score what got through (`agentfox test redteam`).

The attacks are written from the agent's own tools by the attack library the
dashboard's attack test uses (``capabilities/onboarding/attacks.py``), so a seat-booking
agent is attacked through ``update_seat``, not with generic SQL and refund probes. The
built-in generic probes run with ``--builtin``, or when AgentFox knows none of the
agent's tools."""

from __future__ import annotations

from typing import Any

import typer
from rich.markup import escape
from rich.table import Table

from agentfox.apps.cli.commands._shared import _session, console, dashboard_url

redteam_app = typer.Typer(
    help="Attack your own configuration and score what got through.",
    no_args_is_help=True,
)


#: Verdicts that stop or rewrite a call: what "blocked" means for live traffic. None:
#: a finding recorded before the applied verdict was kept.
_STOPS = {"block", "escalate", "redact", "mask", "tokenize", None}
#: Above this many rows the table lists only what wasn't blocked (``--all`` lists all).
_TABLE_ROWS = 25


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
    deployment_probes: bool | None = typer.Option(
        None,
        "--deployment-probes/--no-deployment-probes",
        help="Adaptive mode only: also generate probes from this deployment's own grants, "
        "impacts and bound policies (on by default with --adaptive). The static suite "
        "always runs the built-in probes alone.",
    ),
    sets: str | None = typer.Option(
        None,
        "--sets",
        help="Attack sets to write from the agent's tools, comma-separated (default: the "
        "attack test's defaults). See `agentfox test probes`.",
    ),
    builtin: bool = typer.Option(
        False,
        "--builtin",
        help="Also run the built-in generic probes (they run alone when AgentFox knows "
        "none of the agent's tools).",
    ),
    show_all: bool = typer.Option(
        False, "--all", help="List every probe, not only the ones that weren't blocked."
    ),
    allow_escapes: bool = typer.Option(
        False,
        "--allow-escapes",
        help="Exit 0 even when an attack got through. By default an attack that got through "
        "exits 1, so the command can gate CI; one only a watching rule catches counts, since "
        "live traffic isn't stopped by it.",
    ),
) -> None:
    """Run adversarial probes, written from the agent's own tools, against the deployed
    configuration.

    This measures whether *this configuration* got weaker, against known attack classes.
    It is not a robustness certificate, and `--adaptive` does not make it one: every
    published result says an attacker who adapts eventually gets through.

    An attack got through when live traffic would not stop it today: one only a
    watching (observe-mode) rule catches gets through until that rule blocks. The
    recall line, the verdict and the exit code all count it this way.

    Exits 1 when any attack got through (unless --allow-escapes, for a CI step that
    reports without failing). Probes are simulated:
    their tool calls are evaluated without writing decisions, so they never show up
    in findings or in what `policy simulate` replays. The campaign itself, and a
    finding naming the attacks that got through, are recorded.
    """
    from sqlalchemy import select

    from agentfox.capabilities.evaluation import run_campaign
    from agentfox.capabilities.evaluation.redteam import (
        agent_tool_map,
        agent_tool_probes,
        no_tool_probes_reason,
    )
    from agentfox.capabilities.onboarding.attacks import ATTACK_TYPES, LIBRARY, roles
    from agentfox.core.models import RedTeamFinding

    if deployment_probes and not adaptive:
        console.print(
            "[yellow]--deployment-probes has no effect without --adaptive[/] — the static "
            "suite runs the built-in probes only. Add --adaptive to probe this "
            "deployment's own grants."
        )
    keys = [p.strip() for p in probes.split(",")] if probes else None
    chosen = [s.strip() for s in sets.split(",")] if sets else None
    unknown = [s for s in chosen or [] if s not in LIBRARY]
    if unknown:
        console.print(f"[red]No attack set {', '.join(unknown)}.[/] Sets: {', '.join(LIBRARY)}")
        raise typer.Exit(2)
    with _session() as session:
        from agentfox.core.models import Agent
        from agentfox.platform.registry.service import slugify

        if session.scalar(select(Agent).where(Agent.slug == slugify(agent))) is None:
            known = sorted(session.scalars(select(Agent.slug)))
            console.print(
                f"[red]No agent '{agent}'.[/] "
                + (f"Agents here: {', '.join(known[:12])}" if known else "None registered yet.")
            )
            raise typer.Exit(2)
        slug = slugify(agent)
        written, not_run = ([], []) if adaptive else agent_tool_probes(session, slug, chosen)
        tools = agent_tool_map(session, slug) if written else []
        why_generic = "" if written or adaptive else no_tool_probes_reason(session, slug)
        previous = _previous_summary(session, slug)
        kwargs: dict[str, Any] = {}
        if written:
            # The agent's own probes; the generic ones only when asked for (or named).
            kwargs = {"extra_probes": written, "builtin": builtin or bool(keys)}
        campaign = run_campaign(
            session,
            agent,
            probes=keys,
            adaptive=adaptive,
            budget=budget,
            seed=seed,
            include_deployment_probes=deployment_probes is not False,
            **kwargs,
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
                "category": (f.evidence_json or {}).get("category") or "",
                "description": (f.evidence_json or {}).get("description") or "",
                "verdict": (f.evidence_json or {}).get("verdict"),
                # What live traffic gets now: a watching rule's block is recorded, not applied.
                "applied": (f.evidence_json or {}).get("applied_verdict"),
                "waiting_for": (f.evidence_json or {}).get("waiting_for"),
                "target_class": (f.evidence_json or {}).get("target_class"),
                "expect_blocked": (f.evidence_json or {}).get("expect_blocked", True),
                "over_blocked": (f.evidence_json or {}).get("over_blocked", False),
            }
            for f in findings
        ]

    if written:
        acting = [t["name"] for t in roles(tools).action]
        console.print(
            f"[bold]{agent}[/] — {stats['probes_run']} probes written from its "
            f"{len(tools)} tool{'s' if len(tools) != 1 else ''}"
            + (f" (attacks aim at {', '.join(acting)})" if acting else "")
            + f": {stats.get('attacks_run', stats['probes_run'])} attacks, "
            f"{stats.get('benign_probes_run', 0)} normal requests"
        )
        for skip in not_run:
            console.print(
                f"  [dim]not run: {ATTACK_TYPES.get(skip['type'], skip['type'])}: "
                f"{escape(skip['reason'].removeprefix('Not run: '))}[/]"
            )
    else:
        console.print(
            f"[bold]{agent}[/] — {stats['probes_run']} probes "
            f"({stats.get('attacks_run', stats['probes_run'])} attacks, "
            f"{stats.get('benign_probes_run', 0)} benign controls)"
        )
        if not adaptive:
            console.print(
                "  [dim]No attacks were written through this agent's own tools: "
                f"{escape(why_generic)}. These are the built-in generic probes.[/]"
            )
    watching = [
        r
        for r in rows
        if r["expect_blocked"]
        and not r["succeeded"]
        and (r["applied"] not in _STOPS or r["waiting_for"])
    ]
    # One meaning of "got through" for this line, the verdict and the exit code: what
    # live traffic doesn't stop today. A watching rule's catch is not a stop.
    attacks, through, _ = _live(stats)
    stopped = attacks - through
    console.print(
        f"  recall (attacks stopped) [bold]{stopped / attacks if attacks else 1.0:.0%}[/] — "
        f"[green]{stopped} blocked[/], "
        + (f"[red]{through} got through[/]" if through else "[green]0 got through[/]")
        + (
            f" [yellow]({len(watching)} of them caught by rules that only watch)[/]"
            if watching
            else ""
        )
    )
    if watching:
        console.print(
            f"  [yellow]{len(watching)} caught only by rules that watch:[/] live traffic is "
            "not stopped yet. They stop it once their policy blocks "
            + (
                "(Policies → Libraries in the dashboard, or `agentfox policy enforce <policy>`)"
                if dashboard_url()
                else "(`agentfox policy enforce <policy>`; `agentfox policy list` names them)"
            )
            + (
                " or, for a tool call, once the agent is granted its first tool."
                if any(r["waiting_for"] == "grant" for r in watching)
                else "."
            )
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
        console.print("  escapes by payload kind: " + "  ".join(_escape_cells(by_class)))
    if adaptive_stats.get("observe_mode_policies"):
        console.print(
            "  [yellow]note[/] — "
            f"{', '.join(adaptive_stats['observe_mode_policies'])} bound in observe mode; "
            "probes score the counterfactual verdict, so this campaign cannot see that."
        )

    if written and not show_all:
        console.print(_by_set(rows))
        console.print(
            "  [dim]Checked as live traffic would check them, with no model: an attack "
            "not blocked here reaches the agent, and its model may still resist it. "
            "`agentfox init` runs the same attacks against the real agent. --all lists "
            "every probe.[/]"
        )
    else:
        _probe_table(rows, written=bool(written), show_all=show_all)

    console.print(f"\n{_verdict(stats, previous)}")

    if through and not allow_escapes:
        console.print(
            f"\n[bold red]{through} attack(s) got through[/] — exit 1."
            + (
                f" {len(watching)} of them stop once the rules that watch them block."
                if watching
                else ""
            )
            + " [dim]Pass --allow-escapes to report without failing.[/]"
        )
        raise typer.Exit(1)


def _probe_table(rows: list[dict[str, Any]], *, written: bool, show_all: bool) -> None:
    """One line per probe (above `_TABLE_ROWS`, only those not blocked, unless --all)."""
    from agentfox.capabilities.onboarding.attacks import ATTACK_TYPES

    table = Table(box=None, pad_edge=False)
    columns = (
        ("probe", "set", "what it tries", "verdict", "result")
        if written
        else ("probe", "severity", "OWASP", "verdict", "result")
    )
    for column in columns:
        table.add_column(column, style="bold" if column == "probe" else None)
    listed = 0
    for row in rows:
        result, blocked = _result(row)
        if blocked and not show_all and len(rows) > _TABLE_ROWS:
            continue
        listed += 1
        if written:
            cells = (
                row["probe"].removeprefix("agent."),
                ATTACK_TYPES.get(row["category"], row["category"].replace("_", " ")),
                escape(row["description"].removeprefix("Tries to get it to: ")[:60] or "—"),
            )
        else:
            cells = (row["probe"], row["severity"], row["owasp"] or "—")
        table.add_row(*cells, row["verdict"] or "—", result)
    if listed:
        console.print(table)
    if listed < len(rows):
        console.print(
            f"  [dim]{len(rows) - listed} blocked or allowed as expected, not listed "
            "(--all lists them).[/]"
        )


def _by_set(rows: list[dict[str, Any]]) -> Table:
    """Per attack set: attacks, blocked, got through (live traffic isn't stopped) and
    how many of those a watching rule catches, and the set's normal requests answered /
    blocked. "Got through" counts as the recall line, the verdict and the exit code do."""
    from agentfox.capabilities.onboarding.attacks import ATTACK_TYPES

    sets: dict[str, dict[str, int]] = {}
    for row in rows:
        target = str(row.get("target_class") or "")
        kind = target.rsplit(".", 1)[-1] if ".control." in target else row["category"]
        n = sets.setdefault(
            kind,
            {"attacks": 0, "blocked": 0, "watching": 0, "through": 0, "normal": 0, "over": 0},
        )
        result, _ok = _result(row)
        if not row["expect_blocked"]:
            n["normal"] += 1
            n["over"] += int("OVER-BLOCKED" in result)
            continue
        n["attacks"] += 1
        if "NOT BLOCKED" in result:
            n["through"] += 1
        elif "would block" in result:
            n["through"] += 1
            n["watching"] += 1
        else:
            n["blocked"] += 1
    table = Table(box=None, pad_edge=False)
    for column in (
        "set",
        "attacks",
        "blocked",
        "got through",
        "of those, watched",
        "normal requests",
    ):
        table.add_column(column, justify="left" if column == "set" else "right")
    for kind, n in sets.items():
        table.add_row(
            ATTACK_TYPES.get(kind, kind.replace("_", " ")),
            str(n["attacks"]),
            f"[green]{n['blocked']}[/]" if n["blocked"] else "0",
            f"[red]{n['through']}[/]" if n["through"] else "0",
            f"[yellow]{n['watching']}[/]" if n["watching"] else "0",
            (f"{n['normal'] - n['over']} of {n['normal']} answered" if n["normal"] else "—")
            + (f", [red]{n['over']} blocked[/]" if n["over"] else ""),
        )
    return table


def _result(row: dict[str, Any]) -> tuple[str, bool]:
    """A finding's result cell, and whether it was blocked (or allowed) as it should be."""
    if row["over_blocked"]:
        if row["applied"] not in _STOPS:
            return "[yellow]would block (watching): a normal request[/]", False
        return "[red]OVER-BLOCKED (false positive)[/]", False
    if row["expect_blocked"] and row["succeeded"]:
        return "[red]NOT BLOCKED (attack succeeded)[/]", False
    if row["expect_blocked"] and row["waiting_for"] == "grant":
        return "[yellow]got through: would block (waiting for the first tool grant)[/]", False
    if row["expect_blocked"] and row["applied"] not in _STOPS:
        return "[yellow]got through: would block (watching)[/]", False
    if row["expect_blocked"]:
        return "[green]blocked[/]", True
    return "[green]allowed[/]", True


def _live(stats: dict[str, Any]) -> tuple[int, int, int]:
    """(attacks, got through live traffic now, would be stopped once watching rules
    block), from a campaign summary (one from before these were kept: blocked = live)."""
    attacks = int(stats.get("attacks_run", stats.get("probes_run", 0)) or 0)
    through = stats.get("attacks_through_live")
    if through is None:
        through = int(stats.get("attacks_succeeded") or 0)
    return attacks, int(through), int(stats.get("attacks_watching") or 0)


def _verdict(stats: dict[str, Any], previous: dict[str, Any] | None) -> str:
    """One line, like the dashboard's before → after: how many attacks get through live
    traffic today, how many more stop once the watching rules block, and how normal
    requests fared."""
    attacks, through, watching = _live(stats)
    if not attacks:
        return "[bold]Verdict:[/] no attack ran, so this says nothing about the agent yet."
    colour = "red" if through else "green"
    line = f"[bold]Verdict:[/] [{colour}]{through} of {attacks} attacks get through[/] today"
    comparable = (
        previous is not None
        and _live(previous)[0] == attacks
        and int(previous.get("tool_probes") or 0) == int(stats.get("tool_probes") or 0)
    )
    if comparable and previous is not None:
        line += f" (last run: {_live(previous)[1]} → now {through})"
    if watching:
        line += f"; {through - watching} once the watching rules block"
    controls = int(stats.get("benign_probes_run") or 0)
    if controls:
        blocked = int(
            stats.get("benign_over_blocked_live", stats.get("benign_false_positives")) or 0
        )
        line += f". {controls - blocked} of {controls} normal requests answered"
        line += f", {blocked} blocked" if blocked else ""
    return line + "."


def _previous_summary(session: Any, slug: str) -> dict[str, Any] | None:
    """The summary of the agent's last finished static campaign, to compare against."""
    from sqlalchemy import select

    from agentfox.core.models import RedTeamCampaign

    for campaign in session.scalars(
        select(RedTeamCampaign)
        .where(RedTeamCampaign.status == "completed")
        .order_by(RedTeamCampaign.created_at.desc())
        .limit(50)
    ):
        target = campaign.target_json or {}
        if target.get("agent") == slug and not target.get("adaptive"):
            return dict(campaign.summary_json or {})
    return None


def _escape_cells(by_class: dict) -> list[str]:
    """``readable 0/8  requires_decode 2/3 (67%)`` rather than the raw stats dicts."""
    cells = []
    for name, value in sorted(by_class.items()):
        if isinstance(value, dict):
            escapes, attempts = value.get("escapes", 0), value.get("attempts", 0)
            rate = value.get("escape_rate")
            cell = f"{name} {escapes}/{attempts}"
            if escapes and rate is not None:
                cell += f" ({rate:.0%})"
            cells.append(cell)
        else:
            cells.append(f"{name} {value}")
    return cells


@redteam_app.command("probes")
def redteam_probes() -> None:
    """List the probe suite (built in, and from capability packs) and the wrapped runners."""
    from agentfox.capabilities.evaluation.redteam import available_probes, available_runners

    table = Table(box=None, pad_edge=False)
    for column in ("probe", "category", "surface", "severity", "OWASP", "ATLAS"):
        table.add_column(column, style="bold" if column == "probe" else None)
    for probe in available_probes():
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
