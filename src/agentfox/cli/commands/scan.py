"""`agentfox scan` — snapshot skills and MCP servers and check them for hygiene."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer
from rich.panel import Panel

from agentfox.cli._style import SEVERITY_COLOUR
from agentfox.cli.commands._shared import _session, console

scan_app = typer.Typer(
    help="Snapshot an MCP server's tools and check them for hygiene.",
    no_args_is_help=True,
)


@scan_app.command("skills")
def scan_skills(
    path: Path = typer.Argument(Path("."), help="Directory to search for SKILL.md files."),
    persist: bool = typer.Option(
        True, "--persist/--no-persist", help="Raise findings, or just print."
    ),
) -> None:
    """Scan agent skills for planted instructions and declared danger.

    A skill is the same object as an MCP tool one layer up: a description the
    model reads to decide whether to invoke it, and instructions it then obeys.
    OWASP published an Agentic Skills Top 10 in 2026 and we scanned servers but
    not skills.
    """
    from agentfox.platform.ledger.findings import raise_finding
    from agentfox.platform.registry.skills import scan_skills_dir

    results = scan_skills_dir(path)
    if not results:
        console.print(f"[dim]no SKILL.md files under {path}[/]")
        return

    total = 0
    for result in results:
        issues = result["issues"]
        total += len(issues)
        head = f"[bold]{result['skill']}[/]  [dim]{result['path']}[/]"
        if not issues:
            console.print(f"{head}\n  [green]clean[/]")
            continue
        console.print(head)
        for issue in issues:
            colour = SEVERITY_COLOUR.get(issue["severity"], "dim")
            extra = issue.get("risk") or issue.get("location") or ""
            console.print(
                f"  [{colour}]{issue['severity']}[/] {issue['type']}"
                + (f" — {extra}" if extra else "")
            )
            if issue.get("excerpt"):
                console.print(f"      [dim]{issue['excerpt'][:160]}[/]")

    if persist:
        with _session() as session:
            for result in results:
                for issue in result["issues"]:
                    raise_finding(
                        session,
                        type=issue["type"],
                        severity=issue["severity"],
                        title=f"Skill '{result['skill']}': {issue['type'].replace('_', ' ')}",
                        subject_type="skill",
                        subject_id=None,
                        evidence={**issue, "path": result["path"], "digest": result["digest"]},
                        control_keys=["NOM-DSC-05"],
                        fingerprint_parts=(result["skill"], issue["type"], issue.get("risk")),
                    )

    console.print(
        f"\n  {len(results)} skill(s) · {total} issue(s)"
        + ("" if persist else "  [dim](not recorded: --no-persist)[/]")
    )
    # Said plainly rather than left to be discovered: this is a static read.
    console.print(
        "  [dim]Static: nothing here runs a skill or reads its bundled scripts, and a "
        "skill that describes dangerous behaviour in plain prose is not caught.[/]"
    )
    if total:
        raise typer.Exit(1)


@scan_app.command("mcp")
def scan_mcp(
    server: str | None = typer.Argument(
        None, help="Server name as your MCP config declares it. Omit to scan every one."
    ),
    file: Path | None = typer.Option(
        None, "--file", help="Tool list JSON (what the server's tools/list returned)."
    ),
    config: Path | None = typer.Option(
        None,
        "--config",
        help="MCP client config to read servers from. Default: the first of .mcp.json, "
        ".cursor/mcp.json, .claude/settings.json, .claude.json and "
        "claude_desktop_config.json found in this directory.",
    ),
    seed_fixture: bool = typer.Option(
        False,
        "--seed-fixture",
        help="Scan the built-in demo tool list instead of --file. For demos only.",
    ),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable output for scripts."),
) -> None:
    """Check an MCP server: what it can reach, how it is pinned, and its tools.

    Reads your MCP client config and registers every server it declares, so there is
    nothing to set up first. Nothing is started: without --file the check covers
    what the config shows (version pinning, remote auth, credentials in the file) and
    what the server can reach. With --file (the server's tools/list output) it also
    snapshots the tools and flags poisoned descriptions and changes since last time.
    """
    from sqlalchemy import select

    from agentfox.core.models import McpServer
    from agentfox.discovery.exposure import (
        FLAG_LABEL,
        Member,
        classify_mcp_server,
        classify_tool,
        find_mcp_configs,
        parse_mcp_config,
        server_hygiene,
        trifecta_sentence,
    )
    from agentfox.fixtures.seed import MCP_TOOLS
    from agentfox.monitoring.service import safe_ensure_monitor
    from agentfox.platform.registry.service import (
        normalise_tool_list,
        scan_mcp_server,
        upsert_mcp_server,
    )

    if file is not None and seed_fixture:
        console.print("[red]pass either --file or --seed-fixture, not both[/]")
        raise typer.Exit(2)
    if config is not None and not config.is_file():
        console.print(f"[red]no such config file:[/] {config}")
        raise typer.Exit(2)

    root = Path(".")
    configs = [config] if config is not None else find_mcp_configs(root)
    declared = {}
    for path in configs:
        for decl in parse_mcp_config(path, root=root):
            declared.setdefault(decl.name, decl)

    tools = MCP_TOOLS if seed_fixture else None
    if file is not None:
        try:
            tools = normalise_tool_list(json.loads(file.read_text()))
        except FileNotFoundError:
            console.print(f"[red]no such file:[/] {file}")
            raise typer.Exit(2) from None
        except (json.JSONDecodeError, ValueError) as exc:
            console.print(f"[red]{file} is not a tools/list result:[/] {exc}")
            raise typer.Exit(2) from None
    if server is None and tools is not None:
        console.print("[red]name the server the tool list belongs to[/]")
        raise typer.Exit(2)

    with _session() as session:
        # Every declared server is registered, so a fresh repo needs no setup step.
        # An existing record keeps the trust level an operator gave it.
        for decl in declared.values():
            existing = session.scalar(select(McpServer).where(McpServer.name == decl.name))
            record = upsert_mcp_server(
                session,
                decl.name,
                url=decl.url,
                transport=decl.transport,
                trust_level=existing.trust_level if existing else "untrusted",
                pinned_version=decl.pinned_version,
            )
            # Registered means watched: `agentfox scan monitors list` shows it.
            safe_ensure_monitor(
                session,
                kind="mcp_server",
                target=record.name,
                config={"mcp_server_id": record.id},
                created_by="cli",
            )
        names = [server] if server else sorted(declared)
        if not names:
            where = str(config) if config else "this directory"
            console.print(
                f"[yellow]No MCP servers declared in {where}.[/] Looked for: "
                + ", ".join(f"[dim]{c}[/]" for c in _MCP_CONFIG_HINT)
                + ". Pass [cyan]--config PATH[/] to point at another one."
            )
            raise typer.Exit(2)

        results = []
        for name in names:
            decl = declared.get(name)
            record = session.scalar(select(McpServer).where(McpServer.name == name))
            if record is None and tools is not None:
                # A tool list is enough to know the server exists; registering it is
                # this command's job, not a separate step the user has to find.
                record = upsert_mcp_server(session, name)
            if record is None:
                searched = str(config) if config else ", ".join(_MCP_CONFIG_HINT)
                console.print(
                    f"[red]no MCP server named '{name}'[/] in {searched}. "
                    "Pass [cyan]--config PATH[/] to the config that declares it, or "
                    "[cyan]--file tools.json[/] with its tools/list output."
                )
                raise typer.Exit(2)
            entry: dict[str, Any] = {"server": name, "declared_in": decl.config if decl else None}
            if decl is not None:
                caps = classify_mcp_server(decl)
                entry.update(
                    launch=decl.launch,
                    pinned_version=decl.pinned_version,
                    known=caps.known,
                    capabilities=caps.ordered(),
                    reaches=[caps.phrases.get(f, FLAG_LABEL[f]) for f in caps.ordered()],
                    config_issues=server_hygiene(decl),
                )
            if tools is not None:
                result = scan_mcp_server(session, record, tools)
                per_tool = []
                for tool in tools:
                    tool_caps = classify_tool(
                        str(tool.get("name", "")), tool.get("description", "")
                    )
                    per_tool.append({"name": tool.get("name"), "capabilities": tool_caps.ordered()})
                entry.update(
                    tools=result["tools"],
                    digest=result["digest"],
                    issues=result["issues"],
                    tool_capabilities=per_tool,
                    external_scan=result["external_scan"],
                )
            results.append(entry)

    # Servers declared side by side share a client, and so share a model: together
    # they can form a lethal trifecta that none of them is on its own.
    trifecta = None
    if not server and len(declared) > 1:
        members = [Member(d.name, classify_mcp_server(d), d.config, 1) for d in declared.values()]
        unknown = [m.name for m in members if not m.caps.known]
        found = trifecta_sentence(
            configs[0].name if len(configs) == 1 else "these MCP configs",
            members,
            unknown=unknown,
        )
        trifecta = found[0] if found else None

    # Critical means stop: a poisoned tool description, a critical config issue, or
    # a lethal trifecta across the declared servers. Exit 1 so a CI step fails on it
    # the way `scan skills` already does.
    critical = bool(trifecta) or any(
        issue.get("severity") == "critical"
        for entry in results
        for issue in [*entry.get("issues", []), *entry.get("config_issues", [])]
    )

    if as_json:
        console.print_json(
            json.dumps(
                {"servers": results, "lethal_trifecta": trifecta, "critical": critical},
                default=str,
            )
        )
        if critical:
            raise typer.Exit(1)
        return

    if trifecta:
        console.print(
            Panel(
                trifecta,
                title="[bold red]CRITICAL · lethal trifecta[/]",
                title_align="left",
                border_style="red",
            )
        )
    for entry in results:
        console.print(
            f"[bold]{entry['server']}[/]"
            + (f"  [dim]{entry['declared_in']}[/]" if entry.get("declared_in") else "")
        )
        if entry.get("launch"):
            console.print(f"  [dim]runs:[/] {entry['launch']}")
        if "known" in entry:
            if not entry["known"]:
                console.print(
                    "  [yellow]can reach: unknown[/] — not a server AgentFox recognises. "
                    f"Give it the tool list: [cyan]agentfox scan mcp {entry['server']} "
                    "--file tools.json[/]"
                )
            elif entry["reaches"]:
                console.print(f"  [dim]can reach:[/] {'; '.join(entry['reaches'])}")
            else:
                console.print("  [dim]can reach:[/] nothing private, nothing outside")
            for issue in entry["config_issues"]:
                colour = SEVERITY_COLOUR.get(issue["severity"], "dim")
                console.print(f"  [{colour}]{issue['severity']}[/] {issue['detail']}")
        if "tools" not in entry:
            console.print(
                "  [dim]tools: not listed — nothing was started. Save the server's "
                f"tools/list output and run[/] [cyan]agentfox scan mcp {entry['server']} "
                "--file tools.json[/] [dim]to check each tool's description.[/]"
            )
            continue
        console.print(f"  {entry['tools']} tools, digest {entry['digest'][:16]}…")
        risky = [t for t in entry["tool_capabilities"] if t["capabilities"]]
        for tool in risky[:10]:
            flags = ", ".join(FLAG_LABEL[f] for f in tool["capabilities"])
            console.print(f"    [dim]{tool['name']}:[/] {flags}")
        if not [i for i in entry["issues"] if i["type"] != "unpinned_server"]:
            console.print("  [green]no tool issues[/]")
        config_types = {i["type"] for i in entry.get("config_issues", [])}
        for issue in entry["issues"]:
            if issue["type"] in config_types:
                continue  # already said above, from the config
            colour = SEVERITY_COLOUR.get(issue["severity"], "dim")
            text = _MCP_ISSUE_TEXT.get(issue["type"], issue["type"].replace("_", " "))
            console.print(
                f"  [{colour}]{issue['severity']}[/] {text}"
                + (f" — {issue.get('tool')}" if issue.get("tool") else "")
            )
            if issue.get("excerpt"):
                console.print(f"      [dim]{issue['excerpt'][:120]}[/]")
        external = entry["external_scan"]
        if not external["ran"]:
            console.print("  [dim]mcp-scan: not installed (optional external scanner)[/]")
    if critical:
        console.print("\n[bold red]critical issue(s) found[/] — exit 1")
        raise typer.Exit(1)


#: Where `scan mcp` looked, for the message when it found nothing.
_MCP_CONFIG_HINT = (
    ".mcp.json",
    ".cursor/mcp.json",
    ".claude/settings.json",
    ".claude.json",
    "claude_desktop_config.json",
)


#: Hygiene issue types as a sentence, so the output does not read like an enum.
_MCP_ISSUE_TEXT = {
    "schema_drift": "tools changed since the last scan",
    "tool_poisoning": "instructions hidden in a tool description",
    "unpinned_server": "no version pinned — its tools can change silently",
}


# `agentfox scan monitors …` — the scheduled counterpart of every scan above.
from agentfox.cli.commands.monitors import monitors_app  # noqa: E402

scan_app.add_typer(monitors_app, name="monitors")
