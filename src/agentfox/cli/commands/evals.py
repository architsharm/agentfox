"""`agentfox eval` — score an agent, gate a build on regression, watch for drift."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

import typer
from rich.table import Table

from agentfox.cli.commands._shared import _session, console

eval_app = typer.Typer(
    help="Score an agent, fail the build on a regression, watch for drift.",
    no_args_is_help=True,
)


def _unknown_suite(session: Any, suite: str) -> None:
    """Name the suites that do exist.

    A required positional whose valid values live in a database table is
    undiscoverable otherwise — `policy enforce` already lists its options on the
    same mistake, and there is no reason this one should not.
    """
    from sqlalchemy import select

    from agentfox.core.models import EvalSuite

    known = sorted(k for k in session.scalars(select(EvalSuite.key)))
    console.print(f"[red]unknown suite '{suite}'[/]")
    if known:
        console.print(f"  known suites: {', '.join(known)}")
    else:
        console.print("  no suites exist yet — `agentfox admin seed` creates one to try.")


@eval_app.command("suites")
def eval_suites() -> None:
    """List the evaluation suites in this deployment."""
    from sqlalchemy import func, select

    from agentfox.core.models import EvalCase, EvalSuite

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
        console.print("[dim]no evaluation suites — `agentfox admin seed` creates one to try.[/]")
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

    from agentfox.core.models import EvalSuite
    from agentfox.evaluation.runner import NativeEvalRunner, fit_envelope

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
        console.print(f"  [dim]run {run_id} · `agentfox test baseline {run_id}` to pin it[/]")
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
    """Run the suite and fail the build on regression. Exits 1 on failure."""
    from sqlalchemy import select

    from agentfox.core.models import EvalSuite
    from agentfox.evaluation import gate, to_junit, to_sarif
    from agentfox.evaluation.runner import NativeEvalRunner

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
                f"  [dim]arm it: `agentfox test baseline {run_id}`, or pass "
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
    from agentfox.core.models import EvalRun
    from agentfox.evaluation import set_baseline

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
    from agentfox.evaluation import compute_drift

    with _session() as session:
        report = compute_drift(session, agent, scorer)
    if report is None:
        console.print("[yellow]insufficient online samples[/] — run `agentfox test online` first")
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
    """Sample production traffic and score it with the offline scorers."""
    from agentfox.evaluation import sample_production

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
