"""What `agentfox up` can set up, one component per line of the "what to include" list.

A component has three parts:

* ``unavailable`` — why it cannot be picked here (a remote target, no Enterprise, no
  GitHub remote), or "" when it can. Shown greyed out with the reason, so a person
  sees what exists and what it would take, rather than a shorter list.
* ``ask`` — its follow-up questions. All of them run before anything is changed, so
  a person answers everything first and then watches it happen.
* ``apply`` — the change itself, through the run's backend. A failure is reported
  and the next component still runs.

Defaults come from the scan: a component is pre-ticked when the repository shows a
reason for it.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from rich.console import Console
from rich.markup import escape

from agentfox.apps.cli.wizard.backend import BackendError, Edition
from agentfox.apps.cli.wizard.detect import STATE_DIR, Context
from agentfox.apps.cli.wizard.prompt import Choice, Prompter
from agentfox.apps.cli.wizard.targets import Target

IMPACTS = ("read", "write", "high_impact", "irreversible")

#: Safety modes: the second question, after what to include.
MODES = (
    Choice(
        "observe",
        "Watch first",
        "Record every decision, block nothing. Promote to enforce once it looks right.",
    ),
    Choice(
        "defaults",
        "Shipped defaults",
        "Tool containment blocks from the start; detectors watch.",
    ),
    Choice(
        "enforce",
        "Enforce everything",
        "Every policy blocks what it would block. For a project you already trust.",
    ),
)


@dataclass
class Outcome:
    component: str
    status: str  # "done" | "skipped" | "failed"
    detail: str


@dataclass
class Run:
    ctx: Context
    target: Target
    prompter: Prompter
    console: Console
    agent: str
    mode: str = "observe"
    #: Start background processes (hook daemon, local API). Off for --no-start and tests.
    start: bool = True
    interactive: bool = False
    #: Per-component answers from `ask`, keyed by component key.
    answers: dict[str, Any] = field(default_factory=dict)
    env: dict[str, str] = field(default_factory=dict)
    outcomes: list[Outcome] = field(default_factory=list)
    next_steps: list[tuple[str, str]] = field(default_factory=list)
    running: list[str] = field(default_factory=list)
    _edition: Edition | None = field(default=None, repr=False)

    @property
    def edition(self) -> Edition:
        """What the control plane can do, asked once."""
        if self._edition is None:
            try:
                self._edition = self.target.backend.edition()
            except BackendError:
                self._edition = Edition("open-source")
        return self._edition

    def say(self, text: str) -> None:
        self.console.print(f"    {text}")

    def done(self, component: str, detail: str) -> None:
        self.outcomes.append(Outcome(component, "done", detail))
        self.console.print(f"  [green]✓[/] {detail}")

    def skipped(self, component: str, detail: str) -> None:
        self.outcomes.append(Outcome(component, "skipped", detail))
        self.console.print(f"  [dim]–[/] {detail}")

    def failed(self, component: str, detail: str) -> None:
        self.outcomes.append(Outcome(component, "failed", detail))
        self.console.print(f"  [red]✗[/] {escape(detail)}")


@dataclass
class Component:
    key: str
    label: str
    note: Callable[[Run], str]
    unavailable: Callable[[Run], str]
    recommended: Callable[[Run], bool]
    apply: Callable[[Run], None]
    ask: Callable[[Run], None] | None = None


def _never(_run: Run) -> str:
    return ""


def _plural(n: int, word: str) -> str:
    if n == 1:
        return f"{n} {word}"
    return f"{n} {word[:-1]}ies" if word.endswith("y") else f"{n} {word}s"


# ---------------------------------------------------------------------------
# Background processes
# ---------------------------------------------------------------------------


def _spawn(run: Run, name: str, args: list[str]) -> bool:
    """Start ``agentfox <args>`` detached, logging to .agentfox/logs/<name>.log."""
    logs = run.ctx.root / STATE_DIR / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    log = (logs / f"{name}.log").open("ab")
    env = {**os.environ, **run.env}
    try:
        process = subprocess.Popen(
            [sys.executable, "-m", "agentfox.apps.cli.main", *args],
            stdout=log,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            cwd=run.ctx.root,
            env=env,
            start_new_session=True,
        )
    except OSError as exc:
        run.say(f"[red]could not start {name}:[/] {exc}")
        return False
    (run.ctx.root / STATE_DIR / f"{name}.pid").write_text(str(process.pid))
    run.running.append(f"{name} (pid {process.pid}, log .agentfox/logs/{name}.log)")
    return True


def _api_up(url: str) -> bool:
    try:
        return httpx.get(f"{url}/api/health", timeout=2).status_code == 200
    except httpx.HTTPError:
        return False


def _ensure_local_api(run: Run) -> bool:
    if _api_up(run.target.api_url):
        return True
    if not run.start:
        run.next_steps.append(("agentfox serve", "the gateway and API, for the integrations above"))
        return False
    if not _spawn(run, "serve", ["serve"]):
        return False
    import time

    for _ in range(40):
        if _api_up(run.target.api_url):
            return True
        time.sleep(0.25)
    return False


# ---------------------------------------------------------------------------
# Scan report
# ---------------------------------------------------------------------------


def _scan_note(run: Run) -> str:
    return "counts and top-level folders only — never code, paths or line numbers"


def _apply_scan(run: Run) -> None:
    payload = run.ctx.report.to_submission_payload(source="check")
    payload["label"] = run.ctx.github_repo or run.ctx.project
    try:
        result = run.target.backend.submit_scan(payload)
    except BackendError as exc:
        run.failed("scan-report", str(exc))
        return
    summary = result.get("summary", {})
    run.done(
        "scan-report",
        f"scan recorded: {_plural(len(summary.get('agents_proposed') or []), 'draft agent')}, "
        f"{_plural(len(summary.get('policies_proposed') or []), 'proposed policy')} to review",
    )


# ---------------------------------------------------------------------------
# Coding agents (Claude Code, Codex)
# ---------------------------------------------------------------------------


def _coding_note(run: Run) -> str:
    present = [h.display for h in run.ctx.harnesses if h.present]
    return (
        f"found {', '.join(present)}" if present else "none found here; installs the hooks anyway"
    )


def _coding_ask(run: Run) -> None:
    harnesses = run.ctx.harnesses
    present = [h.name for h in harnesses if h.present] or [harnesses[0].name]
    if len(harnesses) > 1:
        picked = run.prompter.multiselect(
            "Which coding agents?",
            [Choice(h.name, h.display, "in use here" if h.present else "") for h in harnesses],
            run.ctx.saved.get("harnesses", present),
        )
    else:
        picked = present
    run.answers["coding-agents"] = picked


def _coding_apply(run: Run) -> None:
    from agentfox import harnesses
    from agentfox.core.db import init_db, session_scope
    from agentfox.harnesses.base import InstallError
    from agentfox.harnesses.baseline import install_baseline
    from agentfox.platform.policy.coding import enable_for_agent

    if run.target.remote:
        # The hooks decide on this machine, so they need this machine's packs too.
        from agentfox.apps.cli.onboarding import setup_workspace

        setup_workspace(run.ctx.root, "development", brief=True)
    init_db()
    for name in run.answers.get("coding-agents", []):
        adapter = harnesses.get(name)
        slug = f"{run.agent}-{name}"
        try:
            with session_scope() as session:
                baseline = install_baseline(
                    session, harness=name, agent_slug=slug, environment="development", grant=True
                )
            changes = adapter.install(run.ctx.root, "project", agent=slug)
            for change in changes:
                if change.action != "unchanged":
                    change.apply()
            with session_scope() as session:
                enable_for_agent(session, slug)
        except (InstallError, OSError) as exc:
            run.failed("coding-agents", f"{adapter.display_name}: {exc}")
            continue
        written = [
            str(c.path.relative_to(run.ctx.root)) for c in changes if c.action != "unchanged"
        ]
        run.done(
            "coding-agents",
            f"{adapter.display_name} hooks → agent [bold]{slug}[/], "
            f"{_plural(len(baseline.tools_granted), 'built-in tool')} granted"
            + (f" [dim]({', '.join(written)})[/]" if written else " [dim](already installed)[/]"),
        )
    if not run.answers.get("coding-agents"):
        return
    from agentfox.hooks import ping

    if ping():
        run.say("[dim]hook daemon already running[/]")
    elif run.start and _spawn(run, "hooks-daemon", ["admin", "hooks", "daemon"]):
        run.say("[green]hook daemon started[/]")
    else:
        run.next_steps.append(
            (
                "agentfox admin hooks daemon",
                "keep it running: the hooks report unchecked without it",
            )
        )
    if run.target.remote:
        run.say(
            "[dim]Hooks decide on this machine and record here; your coding agent's decisions "
            "do not appear in the remote dashboard.[/]"
        )


# ---------------------------------------------------------------------------
# A Python agent: agentfox.auto()
# ---------------------------------------------------------------------------

_AUTO_MARK = "agentfox.auto("


def _python_unavailable(run: Run) -> str:
    if run.target.remote:
        return "auto() records on this machine; pick the gateway option for a remote control plane"
    return ""


def _python_note(run: Run) -> str:
    n = run.ctx.python_calls
    return f"{_plural(n, 'model call')} in Python" if n else "no Python model calls found"


def _python_ask(run: Run) -> None:
    candidates = run.ctx.entry_points
    choices = [
        Choice(str(p.relative_to(run.ctx.root)), str(p.relative_to(run.ctx.root)))
        for p in candidates
    ]
    choices.append(Choice("none", "Don't edit my code", "show the line to add instead"))
    default = run.ctx.saved.get("entry_point") or (choices[0].key if candidates else "none")
    if default not in {c.key for c in choices}:
        default = choices[0].key
    run.answers["python-app"] = run.prompter.select(
        "Add `agentfox.auto()` to which file? (the one that starts your agent)", choices, default
    )


def _auto_lines(run: Run) -> str:
    mode = ', mode="observe"' if run.mode == "observe" else ""
    return f'import agentfox\n\nagentfox.auto("{run.agent}"{mode})  # added by `agentfox up`\n'


def insert_auto(path: Path, block: str) -> bool:
    """Put ``block`` after the module docstring and ``from __future__`` imports, before
    the model clients are imported. False when the file already calls auto()."""
    text = path.read_text()
    if _AUTO_MARK in text:
        return False
    import ast

    lines = text.splitlines(keepends=True)
    at = 0
    try:
        module = ast.parse(text)
    except SyntaxError:
        module = None
    if module is not None:
        for node in module.body:
            docstring = (
                isinstance(node, ast.Expr)
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
                and node is module.body[0]
            )
            future = isinstance(node, ast.ImportFrom) and node.module == "__future__"
            if docstring or future:
                at = node.end_lineno or at
            else:
                break
    elif lines and lines[0].startswith("#!"):
        at = 1
    head, tail = "".join(lines[:at]), "".join(lines[at:]).lstrip("\n")
    if head and not head.endswith("\n"):
        head += "\n"
    path.write_text(f"{head}\n{block}\n{tail}" if head else f"{block}\n{tail}")
    return True


def _python_apply(run: Run) -> None:
    run.target.backend.register_agent(run.agent, environment="development", framework=None)
    choice = run.answers.get("python-app", "none")
    block = _auto_lines(run)
    if choice == "none":
        run.skipped(
            "python-app", f"agent {run.agent} registered; add these lines to your entry point:"
        )
        for line in block.strip().splitlines():
            if line:
                run.say(f"[cyan]{escape(line)}[/]")
        return
    path = run.ctx.root / choice
    try:
        changed = insert_auto(path, block)
    except OSError as exc:
        run.failed("python-app", f"{choice}: {exc}")
        return
    if changed:
        run.done("python-app", f'{choice} now calls [bold]agentfox.auto("{run.agent}")[/]')
    else:
        run.done("python-app", f"{choice} already calls agentfox.auto()")


# ---------------------------------------------------------------------------
# Any language: the gateway
# ---------------------------------------------------------------------------


def _gateway_note(run: Run) -> str:
    where = "your control plane" if run.target.remote else "a local gateway on :8080"
    return f"OpenAI/Anthropic base URL and /v1/guard/tool_call via {where}"


def _gateway_recommended(run: Run) -> bool:
    return run.ctx.other_calls > 0 or (run.target.remote and run.ctx.python_calls > 0)


def _gateway_apply(run: Run) -> None:
    api = run.target.api_url
    run.env.update(
        {
            "OPENAI_BASE_URL": f"{api}/v1",
            "ANTHROPIC_BASE_URL": api,
            "AGENTFOX_AGENT": run.agent,
        }
    )
    run.target.backend.register_agent(run.agent, environment="development", framework=None)
    if not run.target.remote and not _ensure_local_api(run):
        run.say("[yellow]the local gateway is not running yet[/]")
    elif not run.target.remote:
        run.say(f"[green]gateway running[/] at {api}")
    run.done("gateway", f"model clients routed through {api} [dim](.agentfox/agentfox.env)[/]")
    run.say(f"[dim]send the header[/] X-AgentFox-Agent: {run.agent}")
    if run.target.remote:
        run.say(
            "[dim]use your AgentFox API key as the client's API key "
            "(OPENAI_API_KEY / ANTHROPIC_API_KEY = $AGENTFOX_API_TOKEN); the gateway holds "
            "the provider key[/]"
        )


# ---------------------------------------------------------------------------
# Tool containment: declare what was found
# ---------------------------------------------------------------------------


def _tools_unavailable(run: Run) -> str:
    return "" if run.ctx.tool_names else "no tool definitions found in this repository"


def _tools_note(run: Run) -> str:
    return f"{_plural(len(run.ctx.tool_names), 'tool')} found; impact inferred from the name"


def _inferred(run: Run) -> dict[str, str]:
    from agentfox.platform.registry.impact import infer_impact

    details = {s.name: s.detail for s in run.ctx.report.tools if s.name}
    return {
        name: infer_impact(name, {"description": details.get(name, "")}, cautious=True)
        for name in run.ctx.tool_names
    }


def _tools_ask(run: Run) -> None:
    impacts = _inferred(run)
    if run.interactive and run.prompter.confirm(
        f"Review the impact of each of the {len(impacts)} tools now? (otherwise they are "
        "marked inferred, for `agentfox doctor` to flag)",
        default=len(impacts) <= 8,
    ):
        choices = [Choice(i, i) for i in IMPACTS]
        for name in list(impacts):
            impacts[name] = run.prompter.select(f"{name} — what can it do?", choices, impacts[name])
    run.answers["tools"] = impacts


def _tools_apply(run: Run) -> None:
    impacts = run.answers.get("tools") or _inferred(run)
    added = kept = 0
    for name, impact in impacts.items():
        try:
            if run.target.backend.declare_tool(name, impact=impact, description=""):
                added += 1
            else:
                kept += 1
        except BackendError as exc:
            run.failed("tools", str(exc))
            return
    risky = sorted(n for n, i in impacts.items() if i in ("high_impact", "irreversible"))
    run.done(
        "tools",
        f"declared {_plural(added, 'tool')}"
        + (f", kept {kept} already declared" if kept else "")
        + (f" — {len(risky)} irreversible/high-impact: {', '.join(risky[:5])}" if risky else ""),
    )
    run.next_steps.append(
        ("agentfox declare list", "check each inferred impact; fix with `agentfox declare tool`")
    )


# ---------------------------------------------------------------------------
# MCP servers
# ---------------------------------------------------------------------------


def _mcp_decls(run: Run) -> list[Any]:
    from agentfox.capabilities.discovery.exposure import find_mcp_configs, parse_mcp_config

    declared: dict[str, Any] = {}
    for path in find_mcp_configs(run.ctx.root):
        for decl in parse_mcp_config(path, root=run.ctx.root):
            declared.setdefault(decl.name, decl)
    return list(declared.values())


def _mcp_unavailable(run: Run) -> str:
    return "" if run.ctx.mcp_names or _mcp_decls(run) else "no MCP client config in this repository"


def _mcp_note(run: Run) -> str:
    names = sorted({d.name for d in _mcp_decls(run)} | set(run.ctx.mcp_names))
    shown = ", ".join(names[:4]) + ("…" if len(names) > 4 else "")
    return f"register {shown}" + (
        " and watch them for tool drift" if run.edition.enterprise else ""
    )


def _mcp_apply(run: Run) -> None:
    decls = _mcp_decls(run)
    count = 0
    for decl in decls:
        try:
            run.target.backend.register_mcp_server(
                decl.name, url=decl.url, transport=decl.transport
            )
            count += 1
        except BackendError as exc:
            run.failed("mcp", str(exc))
    if count:
        run.done("mcp", f"registered {_plural(count, 'MCP server')}")
        run.next_steps.append(
            ("agentfox scan mcp", "what each server can reach, and how it is pinned")
        )


# ---------------------------------------------------------------------------
# AgentFox inside your AI client
# ---------------------------------------------------------------------------


def _client_unavailable(run: Run) -> str:
    if run.target.remote:
        return "the MCP server reads this machine's database"
    return ""


def _client_apply(run: Run) -> None:
    path = run.ctx.root / ".mcp.json"
    try:
        data = json.loads(path.read_text()) if path.is_file() else {}
    except ValueError:
        run.failed("ai-client", ".mcp.json is not valid JSON; not touching it")
        return
    servers = data.setdefault("mcpServers", {})
    if "agentfox" in servers:
        run.done("ai-client", "AgentFox already in .mcp.json")
        return
    servers["agentfox"] = {"command": "agentfox", "args": ["serve", "mcp"]}
    path.write_text(json.dumps(data, indent=2) + "\n")
    run.done(
        "ai-client", "added AgentFox to .mcp.json — ask your AI client about findings and approvals"
    )


# ---------------------------------------------------------------------------
# Enterprise: monitoring and compliance
# ---------------------------------------------------------------------------


def _enterprise_reason(run: Run, feature: str) -> str:
    if feature in run.edition.features:
        return ""
    if run.target.key == "local":
        return "AgentFox Enterprise — `pip install agentfox ./ee` from the repository, or use Cloud"
    if run.target.key == "self-hosted":
        return "needs AgentFox Enterprise on the server"
    return "not enabled for this workspace"


def _monitor_unavailable(run: Run) -> str:
    reason = _enterprise_reason(run, "monitoring")
    if reason:
        return reason
    return "" if run.ctx.github_repo else "no GitHub remote (origin) to watch"


def _monitor_apply(run: Run) -> None:
    repo = run.ctx.github_repo or ""
    try:
        created = run.target.backend.add_monitor("github_repo", repo, name=repo)
    except BackendError as exc:
        run.failed("monitoring", f"{repo}: {exc}")
        return
    run.done("monitoring", f"watching {repo}" + ("" if created else " (already watched)"))
    if run.target.key == "local":
        run.next_steps.append(("agentfox admin jobs run-due", "put on cron: it runs the monitors"))


def _compliance_apply(run: Run) -> None:
    if run.target.remote:
        run.done(
            "compliance",
            f"posture and evidence: {run.target.dashboard_url or run.target.api_url}"
            "/app/compliance",
        )
        return
    from agentfox.core import extensions
    from agentfox.core.db import init_db, session_scope

    posture = extensions.service("compliance.posture")
    if posture is None:
        run.failed("compliance", "AgentFox Enterprise is not installed")
        return
    init_db()
    with session_scope() as session:
        result = posture(session)
    counts = result.get("counts") or {}
    pending = counts.get("not_computed", 0)
    scored = ", ".join(
        f"{v} {k.replace('_', ' ')}" for k, v in counts.items() if v and k != "not_computed"
    )
    run.done(
        "compliance",
        f"{_plural(result.get('controls', 0), 'control')} loaded"
        + (f": {scored}" if scored else "")
        + (f" [dim]({pending} not scored yet)[/]" if pending else ""),
    )
    if pending:
        run.next_steps.append(
            ("agentfox admin catalog compute", "score every control against what is running")
        )
    run.next_steps.append(
        ("agentfox report", "posture against EU AI Act, ISO 42001, SOC 2, NIST AI RMF")
    )
    run.next_steps.append(
        ("agentfox report evidence", "a signed evidence package an auditor can verify")
    )


# ---------------------------------------------------------------------------
# View
# ---------------------------------------------------------------------------


def _view_note(run: Run) -> str:
    if run.target.dashboard_url:
        return run.target.dashboard_url
    return (
        f"local API and its docs at {run.target.api_url}/docs; "
        "the web dashboard comes with self-hosted or Cloud"
    )


def _view_apply(run: Run) -> None:
    url = run.target.dashboard_url
    if not url:
        if not _ensure_local_api(run):
            run.skipped("view", "local API not started (--no-start)")
            return
        url = f"{run.target.api_url}/docs"
        run.done("view", f"API running at {run.target.api_url} — browse it at {url}")
        run.next_steps.append(("agentfox findings", "what it found, worst first, in the terminal"))
    else:
        url = f"{url}/app"
        run.done("view", f"dashboard: {url}")
    if run.interactive and run.prompter.confirm("Open it in your browser now?", default=True):
        webbrowser.open(url)


# ---------------------------------------------------------------------------
# The catalogue
# ---------------------------------------------------------------------------

CATALOGUE: tuple[Component, ...] = (
    Component(
        "coding-agents",
        "Coding agents — Claude Code / Codex hooks",
        _coding_note,
        _never,
        lambda r: any(h.present for h in r.ctx.harnesses),
        _coding_apply,
        _coding_ask,
    ),
    Component(
        "python-app",
        "Your Python agent — one line, agentfox.auto()",
        _python_note,
        _python_unavailable,
        lambda r: r.ctx.python_calls > 0,
        _python_apply,
        _python_ask,
    ),
    Component(
        "gateway",
        "Any language — route model calls through the gateway",
        _gateway_note,
        _never,
        _gateway_recommended,
        _gateway_apply,
    ),
    Component(
        "tools",
        "Tool containment — declare the tools found",
        _tools_note,
        _tools_unavailable,
        lambda r: bool(r.ctx.tool_names),
        _tools_apply,
        _tools_ask,
    ),
    Component(
        "mcp",
        "MCP servers — register what your clients run",
        _mcp_note,
        _mcp_unavailable,
        lambda r: True,
        _mcp_apply,
    ),
    Component(
        "scan-report",
        "This scan in the dashboard — draft agents and proposed policies",
        _scan_note,
        _never,
        lambda r: True,
        _apply_scan,
    ),
    Component(
        "monitoring",
        "Keep watching — re-check this repo on every push",
        lambda r: r.ctx.github_repo or "",
        _monitor_unavailable,
        lambda r: True,
        _monitor_apply,
    ),
    Component(
        "compliance",
        "Compliance and evidence — EU AI Act, ISO 42001, SOC 2, NIST",
        lambda r: "posture, risk register, signed evidence packages",
        lambda r: _enterprise_reason(r, "compliance"),
        lambda r: True,
        _compliance_apply,
    ),
    Component(
        "ai-client",
        "Ask AgentFox from your AI client — MCP server in .mcp.json",
        lambda r: "findings, approvals and policy, from Claude Code or Cursor",
        _client_unavailable,
        lambda r: False,
        _client_apply,
    ),
    Component(
        "view",
        "Open the dashboard",
        _view_note,
        _never,
        lambda r: True,
        _view_apply,
    ),
)

BY_KEY = {c.key: c for c in CATALOGUE}


def apply_mode(run: Run) -> None:
    """Put the policies in the chosen safety mode."""
    if run.mode == "defaults":
        run.done("mode", "policies left in their shipped modes")
        return
    want = "observe" if run.mode == "observe" else "enforce"
    try:
        modes = run.target.backend.policy_modes()
    except BackendError as exc:
        run.failed("mode", str(exc))
        return
    changed, refused = [], []
    for key, mode in sorted(modes.items()):
        if mode == want:
            continue
        try:
            run.target.backend.set_policy_mode(key, want)
            changed.append(key)
        except BackendError as exc:
            refused.append(f"{key} ({exc})")
    verb = "nothing is blocked yet" if want == "observe" else "every policy blocks"
    run.done(
        "mode",
        f"{_plural(len(modes), 'policy')} in {want} — {verb}"
        + (f" [dim](changed {', '.join(changed)})[/]" if changed else ""),
    )
    for item in refused:
        run.failed("mode", item)
    if want == "observe":
        run.next_steps.append(
            (
                "agentfox policy enforce tool-containment",
                "when the decisions look right: start blocking",
            )
        )
