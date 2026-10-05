"""Authoring and inspecting business guardrails from the command line.

The catalogue commands exist for a specific workflow: someone arrives with a policy
document and has to turn prose into enforcement. `agentfox policy rules suggest` does the
deterministic half of that mapping and `agentfox policy catalogue` shows what can
be expressed at all, which is the question nobody could answer before.

`compile` goes the rest of the way: it reads the document and writes the rules, then
prints what it had to assume and the short list it genuinely could not decide. The
number to watch is the auto-compile rate — the share of governance that became
enforceable without a round-trip to a human.
"""

from __future__ import annotations

import json
from pathlib import Path

import typer
import yaml
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from agentfox.cli._style import SEVERITY_COLOUR

console = Console()


def _session():
    """A session on an initialised database. `init_db` is idempotent, and without it
    a command run before `agentfox init` dies on "no such table"."""
    from agentfox.core.db import init_db, session_scope

    init_db()
    return session_scope()


OUTCOME_COLOUR = {
    "allow": "green",
    "verify": "cyan",
    "redact": "yellow",
    "escalate": "yellow",
    "block": "red",
}


def rules_apply(
    file: Path = typer.Argument(..., help="YAML ladder definition."),
    agent: str | None = typer.Option(None, "--agent"),
    mode: str | None = typer.Option(None, "--mode", help="observe | enforce"),
) -> None:
    """Author or update a business rule from a YAML file."""
    from agentfox.business import Ladder, save_ladder

    try:
        payload = yaml.safe_load(file.read_text())
    except (OSError, yaml.YAMLError) as exc:
        console.print(f"[red]could not read {file}: {exc}[/]")
        raise typer.Exit(1) from exc

    payload.pop("kind", None)
    if mode:
        payload["mode"] = mode
    try:
        ladder = Ladder.model_validate(payload)
    except Exception as exc:
        console.print(f"[red]{file.name} is not a valid ladder:[/] {exc}")
        raise typer.Exit(1) from exc

    with _session() as session:
        save_ladder(session, ladder, agent_slug=agent)

    console.print(
        f"[green]✓[/] [bold]{ladder.key}[/] — {len(ladder.bands)} bands on "
        f"{ladder.field_path} ({ladder.unit})"
    )
    _print_intervals(ladder)
    if ladder.mode == "observe":
        console.print("  [dim]observe mode — the outcome is recorded, not applied.[/]")


def rules_show(key: str | None = typer.Argument(None, help="Rule key; omit for all.")) -> None:
    """Show the resolved bands, so an author sees exactly what they wrote."""
    from agentfox.business import all_ladders

    with _session() as session:
        ladders = [lad for lad in all_ladders(session) if key is None or lad.key == key]

    if not ladders:
        console.print("[dim]No business rules. Author one with `agentfox policy rules apply`.[/]")
        return
    for ladder in ladders:
        console.print(
            f"\n[bold]{ladder.key}[/]  [dim]{ladder.owner or 'no owner'} · {ladder.mode}[/]"
        )
        if ladder.description:
            console.print(f"  [dim]{ladder.description}[/]")
        _print_intervals(ladder)


def _print_intervals(ladder) -> None:
    for lower, upper, band in ladder.intervals():
        low = "−∞" if lower is None else f"{lower:g}"
        high = "∞" if upper is None else f"{upper:g}"
        colour = OUTCOME_COLOUR.get(band.outcome, "dim")
        extra = ""
        if band.verify:
            extra = f" [dim]via {band.verify.check}, on fail → {band.verify.on_fail}[/]"
        elif band.approver_role:
            extra = f" [dim]approver: {band.approver_role}[/]"
        console.print(f"    ({low}, {high}]  →  [{colour}]{band.outcome}[/]{extra}")


def rules_check(as_json: bool = typer.Option(False, "--json")) -> None:
    """Find where two teams' rules disagree.

    Two authors setting different thresholds on the same field is not a merge to be
    resolved by precedence — it is a disagreement between two people, and resolving it
    silently means one of them is wrong and does not know.
    """
    from agentfox.business import all_ladders, find_conflicts

    with _session() as session:
        ladders = all_ladders(session)
        conflicts = find_conflicts(ladders)

    if as_json:
        console.print_json(json.dumps([c.to_json() for c in conflicts]))
        raise typer.Exit(1 if conflicts else 0)

    if not conflicts:
        console.print(f"[green]✓[/] {len(ladders)} rule(s), no conflicts")
        return
    console.print(f"[red]{len(conflicts)} conflict(s)[/] across {len(ladders)} rule(s)\n")
    for conflict in conflicts:
        colour = SEVERITY_COLOUR.get(conflict.severity, "dim")
        console.print(f"  [{colour}]{conflict.severity}[/] {conflict.code}")
        console.print(f"    {conflict.detail}")
        if conflict.left and conflict.right:
            console.print(f"    [dim]between {conflict.left} and {conflict.right}[/]")
    raise typer.Exit(1)


def rules_test(
    key: str = typer.Argument(..., help="Rule key."),
    values: str = typer.Argument(..., help="Comma-separated values to try."),
) -> None:
    """Try values against a rule without running anything."""
    from agentfox.business import all_ladders, evaluate_ladder

    with _session() as session:
        ladder = next((lad for lad in all_ladders(session) if lad.key == key), None)
    if ladder is None:
        console.print(f"[red]unknown rule '{key}'[/]")
        raise typer.Exit(1)

    table = Table(box=None, padding=(0, 2), header_style="dim")
    for column in ("value", "outcome", "why"):
        table.add_column(column)
    for raw in [v.strip() for v in values.split(",") if v.strip()]:
        parts = ladder.field_path.split(".")
        request: dict = {}
        cursor = request
        for part in parts[:-1]:
            cursor[part] = {}
            cursor = cursor[part]
        cursor[parts[-1]] = raw
        decision = evaluate_ladder(ladder, request)
        colour = OUTCOME_COLOUR.get(decision.outcome, "dim")
        table.add_row(raw, f"[{colour}]{decision.outcome}[/]", decision.reason[:64])
    console.print(table)


def catalogue(
    intent: str | None = typer.Option(None, "--intent"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Every kind of guardrail this product can enforce.

    The answer to "can we express our policy?" — asked before anyone writes YAML.
    """
    from agentfox.business.catalogue import CATALOGUE as KINDS
    from agentfox.business.catalogue import to_json

    kinds = [k for k in KINDS if intent is None or k.intent == intent]
    if as_json:
        console.print_json(json.dumps(to_json()))
        return

    table = Table(box=None, padding=(0, 2), header_style="dim")
    table.add_column("kind", no_wrap=True)
    table.add_column("intent", no_wrap=True)
    table.add_column("stage", no_wrap=True)
    table.add_column("decides", overflow="ellipsis", no_wrap=True)
    for kind in kinds:
        table.add_row(
            f"[bold]{kind.id}[/]",
            kind.intent.replace("_", " "),
            kind.stage,
            kind.decides,
        )
    console.print(table)
    console.print(
        f"\n  [dim]{len(kinds)} kind(s). "
        "`agentfox policy rules explain <kind>` for parameters and an example.[/]"
    )


def explain(kind_id: str = typer.Argument(..., help="Guardrail kind id.")) -> None:
    """Parameters, inputs and a worked example for one guardrail kind."""
    from agentfox.business.catalogue import BY_ID

    kind = BY_ID.get(kind_id)
    if kind is None:
        console.print(f"[red]unknown kind '{kind_id}'[/]")
        console.print(f"[dim]try: {', '.join(sorted(BY_ID))}[/]")
        raise typer.Exit(1)

    console.print(
        Panel(
            f"[bold]{kind.name}[/]\n[dim]{kind.decides}[/]\n\n"
            f"[dim]intent[/]  {kind.intent}\n"
            f"[dim]nature[/]  {kind.nature}\n"
            f"[dim]stage [/]  {kind.stage}\n"
            f"[dim]yields[/]  {', '.join(kind.effects) or '—'}",
            title=f"[bold]{kind.id}[/]",
            title_align="left",
            border_style="cyan",
        )
    )
    if kind.inputs:
        console.print("\n  [bold]Needs the request to carry:[/]")
        for need in kind.inputs:
            console.print(f"    · {need}")
        console.print("    [dim]Without these it is configured but inert.[/]")
    if kind.params:
        console.print("\n  [bold]Parameters:[/]")
        for name, description in kind.params.items():
            console.print(f"    [cyan]{name}[/]  [dim]{description}[/]")
    if kind.example:
        console.print("\n  [bold]Example:[/]")
        for line in kind.example.splitlines():
            console.print(f"    [dim]{line}[/]")
    if kind.note:
        console.print(f"\n  [dim]{kind.note}[/]")


def suggest_cmd(
    instruction: str = typer.Argument(..., help="A sentence from a policy document."),
) -> None:
    """Which guardrail kinds a written instruction probably needs.

    Deterministic signal matching, not a model — a starting point an operator confirms,
    so a wrong suggestion costs a glance rather than a silent misconfiguration.
    """
    from agentfox.business.catalogue import suggest

    matches = suggest(instruction, limit=4)
    if not matches:
        console.print("[yellow]No guardrail kind matched that wording.[/]")
        console.print(
            "  [dim]Browse them with `agentfox policy catalogue`. "
            "A policy we cannot express is worth knowing about early.[/]"
        )
        return
    console.print(f'[dim]"{instruction[:76]}"[/]\n')
    for kind, score in matches:
        console.print(f"  [bold cyan]{kind.id}[/]  [dim]{score:.2f} · {kind.decides}[/]")
    console.print(
        f"\n  [dim]`agentfox policy rules explain {matches[0][0].id}` "
        "for parameters and an example.[/]"
    )


def graph() -> None:
    """The decision path as it will actually run, stage by stage."""
    from agentfox.business import all_ladders, build_graph

    with _session() as session:
        ladders = all_ladders(session)
    nodes = build_graph(ladders=ladders)

    current = None
    for node in nodes:
        if node.stage != current:
            current = node.stage
            console.print(f"\n[bold]{current}[/]")
        owner = f" [dim]{node.owner}[/]" if node.owner else ""
        console.print(f"    {node.key:<28}[dim]{node.detail[:56]}[/]{owner}")
    console.print(
        f"\n  [dim]{len(nodes)} guardrail(s) across {len({n.stage for n in nodes})} stages.[/]"
    )


def compile_cmd(
    file: Path = typer.Argument(..., help="Policy document (.txt or .md)."),
    apply: bool = typer.Option(False, "--apply", help="Save the compiled rules."),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Turn a written policy into executable guardrails."""
    from agentfox.business.compile import compile_document
    from agentfox.business.store import save_ladder

    if not file.exists():
        console.print(f"[red]No such file:[/red] {file}")
        raise typer.Exit(1)

    result = compile_document(file.read_text(), key_prefix=file.stem.lower())
    if as_json:
        console.print_json(json.dumps(result.to_json()))
        raise typer.Exit(0)

    rate = result.auto_rate
    colour = "green" if rate >= 0.8 else "yellow" if rate >= 0.5 else "red"
    console.print(
        Panel(
            f"[{colour}]{rate:.0%}[/{colour}] of the governance in this document "
            f"compiled without a question.\n"
            f"{len(result.rules)} rule(s) ready · {len(result.review)} to answer · "
            f"{len(result.unmappable)} not expressible",
            title=f"Compiled {file.name}",
        )
    )

    for rule in result.rules:
        table = Table(box=None, show_header=False, padding=(0, 1))
        table.add_row("[dim]kind[/dim]", rule.kind)
        for key, value in rule.definition.items():
            if key in ("kind", "key", "bands"):
                continue
            table.add_row(f"[dim]{key}[/dim]", str(value))
        console.print(f"\n[bold]{rule.key}[/bold]  [dim]confidence {rule.confidence:.2f}[/dim]")
        console.print(table)
        if bands := rule.definition.get("bands"):
            _print_bands(bands)
        for assumption in rule.assumptions:
            console.print(f"  [yellow]assumed[/yellow] {assumption.what}")
            console.print(f"          [dim]{assumption.why}[/dim]")

    if result.review:
        console.print("\n[bold]Needs a decision[/bold]")
        for item in result.review:
            mark = "[red]blocking[/red]" if item.blocking else "[dim]optional[/dim]"
            console.print(f"  {mark} {item.question}")
            console.print(f"    [dim]{item.why}[/dim]")
            if item.options:
                console.print(f"    [dim]options: {', '.join(item.options)}[/dim]")
            console.print(f"    [dim]from: {item.source[:90]}[/dim]")

    for sentence in result.unmappable:
        console.print(f"\n[dim]not expressible as a guardrail:[/dim] {sentence[:100]}")

    if apply:
        from agentfox.business import Ladder

        ladders = [
            Ladder.model_validate({k: v for k, v in rule.definition.items() if k != "kind"})
            for rule in result.rules
            if rule.kind == "threshold_ladder"
        ]
        with _session() as session:
            for ladder in ladders:
                save_ladder(session, ladder, actor="cli", reason=f"compiled from {file.name}")
        skipped = len(result.rules) - len(ladders)
        console.print(
            f"\n[green]Saved {len(ladders)} ladder(s) in observe mode.[/green] "
            "Run [bold]agentfox policy rules check[/bold], then promote with "
            "[bold]agentfox policy rules apply <ladder.yaml> --mode enforce[/bold]."
        )
        if skipped:
            console.print(
                f"  [dim]{skipped} other rule(s) are not threshold ladders and were not "
                "saved — author them with their own commands.[/dim]"
            )


def _print_bands(bands: list[dict]) -> None:
    for band in bands:
        edge = f"≤ {band['upto']:g}" if "upto" in band else "above"
        outcome = band["outcome"]
        colour = OUTCOME_COLOUR.get(outcome, "white")
        extra = ""
        if verify := band.get("verify"):
            extra = f" via {verify.get('check')}"
        elif role := band.get("approver_role"):
            extra = f" → {role}"
        console.print(f"    [dim]{edge:>10}[/dim]  [{colour}]{outcome}[/{colour}]{extra}")


def register(app: typer.Typer) -> None:
    guardrails_app = typer.Typer(
        help="Business guardrails and the guardrail catalogue.", no_args_is_help=True
    )
    guardrails_app.command(name="apply")(rules_apply)
    guardrails_app.command(name="show")(rules_show)
    guardrails_app.command(name="check")(rules_check)
    guardrails_app.command(name="test")(rules_test)
    guardrails_app.command(name="catalogue")(catalogue)
    guardrails_app.command(name="explain")(explain)
    guardrails_app.command(name="suggest")(suggest_cmd)
    guardrails_app.command(name="graph")(graph)
    guardrails_app.command(name="compile")(compile_cmd)
    app.add_typer(guardrails_app, name="guardrails")
