"""`agentfox policy packs` — the policy files on disk, and the capability packs they ship in.

Bare `agentfox policy packs` is `files`: every policy file this deployment can bind and
where it came from. `list`, `show`, `test` and `validate` are about capability packs
(`src/agentfox/packs/`, installed `agentfox-pack-*` packages, `.agentfox/packs/`).
"""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.table import Table

from agentfox.apps.cli.commands._shared import console
from agentfox.apps.cli.layout import default_group

packs_app = typer.Typer(
    help="Capability packs: the policies, controls, ladders, probes and cases a use case "
    "ships as one directory.\n\n"
    "Bare `agentfox policy packs` lists the policy files on disk and where each came from "
    "(`files`). `list`, `show`, `test` and `validate` work on the packs themselves.",
    cls=default_group("files"),
    no_args_is_help=False,
)

#: Written out rather than interpolated from `project_policy_dir()`, which is
#: absolute: the hint is about what to create, and an absolute path from
#: whatever directory the operator happened to be in reads as a demand.
PROJECT_DIR_HINT = ".agentfox/policies/"


@packs_app.command("files")
def policy_files() -> None:
    """Policy files on disk, and where each came from.

    `policy list` reads the database: what is installed and what mode it is in.
    This reads the filesystem and answers the question an operator has about a
    policy they did not write — which file is this, and did something override
    it. A project pack replacing a shipped one is invisible in `policy list`,
    because by then they are the same row.
    """
    from agentfox.platform.policy import PolicyPackError, pack_sources, project_policy_dir

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


def _resolve(targets: list[str], *, every: bool = False):
    """Packs named by id (or a directory path), or every loaded pack."""
    from agentfox.platform.packs import discover, load_packs, read_pack

    if not targets:
        return [p for p in discover()] if every else load_packs()
    known = {p.id: p for p in discover()}
    out = []
    for target in targets:
        if target in known:
            out.append(known[target])
        elif Path(target).is_dir() and (Path(target) / "pack.yaml").is_file():
            out.append(read_pack(Path(target), "path"))
        else:
            console.print(f"[red]no pack {target!r}[/] — `agentfox policy packs list --all`")
            raise typer.Exit(2)
    return out


@packs_app.command("list")
def packs_list(
    show_all: bool = typer.Option(
        False, "--all", help="Also packs that do not load (maturity, version)."
    ),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Capability packs: built in, installed, and the project's, and whether each loads."""
    from agentfox.platform.packs import discover

    packs = [p for p in discover() if show_all or not p.skipped]
    if as_json:
        console.print_json(json.dumps([p.to_json() for p in packs]))
        return
    table = Table(box=None, pad_edge=False)
    for column in ("pack", "version", "maturity", "origin", "ships"):
        table.add_column(column, style="bold" if column == "pack" else None)
    for pack in packs:
        ships = ", ".join(f"{k} {len(v)}" for k, v in pack.contents().items())
        if pack.manifest.vocabulary:
            ships = ", ".join(filter(None, [ships, "vocabulary"]))
        table.add_row(
            pack.id,
            pack.manifest.version,
            pack.maturity + (f" [dim](not loaded: {pack.skipped})[/]" if pack.skipped else ""),
            f"[cyan]{pack.origin}[/]" if pack.origin != "builtin" else "[dim]builtin[/]",
            ships,
        )
    console.print(table)


@packs_app.command("show")
def packs_show(
    pack_id: str = typer.Argument(..., help="A pack id (payments/refunds) or a pack directory."),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """One pack: its manifest, where it is, and what it ships."""
    (pack,) = _resolve([pack_id], every=True)
    if as_json:
        console.print_json(
            json.dumps({**pack.to_json(), "manifest": pack.manifest.model_dump(mode="json")})
        )
        return
    manifest = pack.manifest
    console.print(f"[bold]{pack.id}[/] {manifest.version}  [dim]{manifest.maturity}[/]")
    if manifest.title:
        console.print(f"  {manifest.title}")
    console.print(f"  [dim]{pack.root}[/]  ({pack.origin})")
    if pack.skipped:
        console.print(f"  [yellow]not loaded:[/] {pack.skipped}")
    console.print(f"  owners       {', '.join(manifest.owners)}")
    if manifest.tags:
        console.print(f"  tags         {', '.join(manifest.tags)}")
    if manifest.requires_core:
        console.print(f"  requires     agentfox {manifest.requires_core}")
    if manifest.compliance.controls:
        console.print(f"  controls     {', '.join(manifest.compliance.controls)}")
    if manifest.requires_detectors:
        console.print(f"  detectors    {', '.join(manifest.requires_detectors)}")
    if manifest.vocabulary:
        console.print(f"  vocabulary   {', '.join(manifest.vocabulary)}")
    if manifest.fallback:
        console.print(
            "  fallback     protects unconfigured deployments at tier(s) "
            + ", ".join(manifest.fallback.risk_tiers)
        )
    for spec in manifest.finding_types:
        console.print(f"  finding type {spec.type} — {spec.title}")
    for folder, names in pack.contents().items():
        console.print(f"  {folder:<12} {', '.join(names)}")


def _print_cases(results) -> None:
    for result in results:
        mark = "[green]✓[/]" if result.passed else "[red]✗[/]"
        line = f"  {mark} {result.pack}  {result.name}"
        if not result.passed:
            line += f"\n      [red]{result.detail}[/]  [dim]({result.file})[/]"
        console.print(line)


@packs_app.command("test")
def packs_test(
    packs: list[str] = typer.Argument(None, help="Pack ids or directories; default all loaded."),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Run each pack's golden cases (`cases/*.yaml`). Exits 1 if any fails."""
    from agentfox.capabilities.evaluation.packs import run_pack_cases

    results = [r for pack in _resolve(packs or []) for r in run_pack_cases(pack)]
    failed = [r for r in results if not r.passed]
    if as_json:
        console.print_json(json.dumps([r.to_json() for r in results]))
    else:
        _print_cases(results)
        colour = "red" if failed else "green"
        console.print(f"\n[{colour}]{len(results) - len(failed)}/{len(results)} case(s) passed[/]")
    if failed:
        raise typer.Exit(1)


@packs_app.command("validate")
def packs_validate(
    packs: list[str] = typer.Argument(None, help="Pack ids or directories; default all."),
    as_json: bool = typer.Option(False, "--json"),
    schema: bool = typer.Option(False, "--schema", help="Print pack.yaml's JSON Schema."),
) -> None:
    """Check a pack: its pack.yaml, that its policies load and lint clean, that its ladders,
    probes, controls and checks are well formed, and that its cases pass. Exits 1 on any
    problem."""
    from agentfox.capabilities.evaluation.packs import validate_pack
    from agentfox.platform.packs import PackManifest

    if schema:
        console.print_json(json.dumps(PackManifest.model_json_schema()))
        return
    reports = [validate_pack(pack) for pack in _resolve(packs or [], every=True)]
    if as_json:
        console.print_json(json.dumps([r.to_json() for r in reports]))
    else:
        for report in reports:
            mark = "[green]✓[/]" if report.ok else "[red]✗[/]"
            passed = sum(c.passed for c in report.cases)
            console.print(f"{mark} [bold]{report.pack}[/]  {passed}/{len(report.cases)} cases")
            for problem in report.problems:
                console.print(f"    [red]{problem}[/]")
            for warning in report.warnings:
                console.print(f"    [yellow]{warning}[/]")
            _print_cases([c for c in report.cases if not c.passed])
    if not all(r.ok for r in reports):
        raise typer.Exit(1)


@packs_app.command("new")
def packs_new(
    pack_id: str = typer.Argument(..., help="The new pack's id, e.g. payments/chargebacks."),
    into: Path = typer.Option(
        Path(".agentfox/packs"),
        "--into",
        help="Where to create it. The default is this project's packs directory.",
    ),
    builtin: bool = typer.Option(
        False, "--builtin", help="Create it among the built-in packs (contributors)."
    ),
) -> None:
    """Scaffold a pack from the template: pack.yaml, a policy, golden cases, a check."""
    import re

    from agentfox.platform.packs import BUILTIN_ROOT, PackManifest

    try:
        PackManifest.model_validate({"id": pack_id, "version": "0.1.0", "owners": ["x"]})
    except ValueError as exc:
        console.print(f"[red]{pack_id!r} is not a pack id[/]: lower-case words, '/'-separated")
        raise typer.Exit(2) from exc
    root = BUILTIN_ROOT if builtin else into
    target = root / pack_id
    if target.exists():
        console.print(f"[red]{target} already exists[/]")
        raise typer.Exit(1)
    name = re.sub(r"[^a-z0-9]+", "_", pack_id.rsplit("/", 1)[-1])
    replacements = {
        "__ID__": pack_id,
        "__TITLE__": pack_id.replace("/", " — ").replace("-", " ").capitalize(),
        "__NAME__": name,
        "__POLICY_KEY__": pack_id.replace("/", "-"),
        "__EXAMPLE_MARKER__": f"{name.upper()}-EXAMPLE",
    }
    template = BUILTIN_ROOT / "_template"
    for source in sorted(template.rglob("*")):
        if source.is_dir() or "__pycache__" in source.parts:
            continue
        relative = str(source.relative_to(template))
        text = source.read_text()
        for placeholder, value in replacements.items():
            relative = relative.replace(placeholder, value)
            text = text.replace(placeholder, value)
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(text)
        console.print(f"  [green]+[/] {destination}")
    console.print(
        f"\nNext: edit {target / 'pack.yaml'}, then `agentfox policy packs validate {target}`."
    )
