"""`agentfox init --key`: map this repo, report it, then stay connected and run
the onboarding's attack tests when the dashboard asks for them.
"""

from __future__ import annotations

import re
import threading
import time
from pathlib import Path
from typing import Any

import httpx
from rich.console import Console
from rich.table import Table

from agentfox.capabilities.onboarding.attacks import build_suite, suite_size
from agentfox.capabilities.onboarding.mapper import map_repository

POLL_SECONDS = 2.0
BATCH_SECONDS = 0.7
#: The longest a running test goes without telling the server it is alive (the server
#: gives up on a run after `runs.LEASE_SECONDS` of silence).
HEARTBEAT_SECONDS = 15.0
#: The first wait before sending a failed report again; it doubles each time.
RETRY_SECONDS = 1.0
#: This many errors and nothing else, from the first attacks, means the model is unreachable.
FAIL_FAST = 6
#: What this runner can do (`schema.Poll.protocol`): 2 checks an "after" test against
#: the project's real policies.
PROTOCOL = 2
TAGS = {
    "got_through": "[red]GOT THROUGH[/red]",
    "stopped": "[cyan]STOPPED[/cyan]",
    "resisted": "[green]RESISTED[/green]",
    "errored": "[yellow]ERROR[/yellow]",
    "not_run": "[dim]NOT RUN[/dim]",
    "allowed": "[green]ALLOWED[/green]",
    "over_blocked": "[magenta]OVER-BLOCKED[/magenta]",
}
RISK_LABEL = {
    "high": "[red]can do real damage[/red]",
    "outside": "[yellow]talks to the outside[/yellow]",
    "read_only": "[dim]read only[/dim]",
}


class ApiError(RuntimeError):
    """The server answered with an error. ``status`` is its HTTP status."""

    def __init__(self, status: int, detail: Any) -> None:
        super().__init__(f"{status}: {detail}")
        self.status = status


class _Api:
    def __init__(self, server: str, key: str) -> None:
        self.http = httpx.Client(
            base_url=server.rstrip("/"), headers={"Authorization": f"Bearer {key}"}, timeout=30
        )

    def post(self, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        from agentfox.core.jsonable import jsonable

        # A check carries what the agent handed its tool: a LangGraph tool's arguments
        # hold the graph's messages (`HumanMessage`), which `json` refuses.
        res = self.http.post(f"/api/onboarding{path}", json=jsonable(body or {}))
        if res.status_code >= 400:
            try:
                detail = res.json().get("detail")
            except ValueError:
                detail = res.text[:200]
            raise ApiError(res.status_code, detail)
        return res.json()


class _Results:
    """A test's results on their way to the server.

    Results leave the queue only once the server has them: a report that fails (the
    network drops, the server restarts) is kept and sent again with the next one. The
    server ignores results it already has, so sending one twice is harmless. A report
    also renews the run's lease, so one goes out at least every ``HEARTBEAT_SECONDS``
    even when no attack has finished. The server answering 409 means the run is over
    (finished, or given up on as stalled): ``closed`` is then set and nothing more is
    sent.
    """

    def __init__(self, api: Any, run_id: str) -> None:
        self.api = api
        self.path = f"/runner/runs/{run_id}/results"
        self.pending: list[dict[str, Any]] = []
        self.lock = threading.Lock()
        self.closed = False
        self.last_sent = time.monotonic()

    def add(self, result: dict[str, Any]) -> None:
        with self.lock:
            self.pending.append(result)

    def _send(self, body: dict[str, Any]) -> bool:
        try:
            self.api.post(self.path, body)
        except ApiError as exc:
            if exc.status == 409:
                self.closed = True
            return False
        except (httpx.HTTPError, RuntimeError, OSError):
            return False
        self.last_sent = time.monotonic()
        return True

    def flush(self, done: bool = False, *, heartbeat: bool = False) -> bool:
        """Send what is waiting (and ``done``). True when the server has it all."""
        if self.closed:
            return False
        with self.lock:
            batch = list(self.pending)
        if not (batch or done or heartbeat):
            return True
        if not self._send({"results": batch, "done": done}):
            return False
        with self.lock:
            del self.pending[: len(batch)]
        return True

    def tick(self) -> None:
        """One beat of the background sender."""
        self.flush(heartbeat=time.monotonic() - self.last_sent >= HEARTBEAT_SECONDS)

    def finish(self, *, error: str | None = None, attempts: int = 5) -> bool:
        """Deliver the rest and close the run (done, or failed with ``error``),
        retrying with a growing wait."""
        for attempt in range(attempts):
            if self.flush() and self._send(
                {"error": error} if error else {"results": [], "done": True}
            ):
                return True
            if self.closed:
                return False
            time.sleep(min(2**attempt, 10) * RETRY_SECONDS)
        return False


def connect(key: str, server: str, path: str | Path = ".", console: Console | None = None) -> None:
    import os

    from agentfox.core.vocab import ATTACK_TEST_ENV

    console = console or Console()
    # The attack test imports the app; the agentfox.auto() line in it must not report
    # the attacks as the app's traffic. Only while this runs.
    previous = os.environ.get(ATTACK_TEST_ENV)
    os.environ[ATTACK_TEST_ENV] = "1"
    try:
        root = Path(path).resolve()
        api = _Api(server, key)
        mapped = report(api, console, root, server, key)
        console.print(
            "[dim]Keep this running: it runs the attack tests on this machine when you "
            "start them. Ctrl-C to stop.[/dim]\n"
        )
        _poll_forever(api, console, root, mapped, mapped["structure"])
    finally:
        if previous is None:
            os.environ.pop(ATTACK_TEST_ENV, None)
        else:
            os.environ[ATTACK_TEST_ENV] = previous


def report(api: Any, console: Console, root: Path, server: str, key: str) -> dict[str, Any]:
    """Map the repository, report it to the account, and connect the app's traffic.
    Returns the map."""
    console.print(f"\n[bold]AgentFox[/bold] · mapping [cyan]{root.name}[/cyan]\n")
    mapped = map_repository(root)
    structure = mapped["structure"]
    _print_map(console, structure)
    _print_coverage(console, mapped)
    if not structure["agents"]:
        console.print(
            "[yellow]No agent found here.[/yellow] "
            "Run this in the repo where your agent is defined."
        )

    try:
        connected = api.post(
            "/runner/connect", {"structure": structure, "project": mapped.get("project")}
        )
    except ApiError as exc:
        if exc.status in (401, 403):
            # Reached, and refused: "couldn't reach" sent people to check the network.
            console.print(
                f"[red]{server} rejected this key ({exc.status}).[/red] It is wrong, revoked "
                "or expired, or its owner may not add agents. Make a new one in the "
                "dashboard: Get started → Create a key, then run this again."
            )
        else:
            console.print(f"[red]AgentFox at {server} refused the connection:[/red] {exc}")
        raise SystemExit(1) from exc
    except (httpx.HTTPError, RuntimeError) as exc:
        console.print(
            f"[red]Couldn't reach AgentFox at {server}[/red] ({type(exc).__name__}). "
            "Check the address (--server) and your network."
        )
        raise SystemExit(1) from exc
    if structure["agents"]:
        console.print(
            "[green]●[/green] Connected. Open AgentFox to add the agents it found and see them."
        )
        # The server keeps no file paths; which file each agent is in, and its name in
        # that file, are known here.
        attrs = {r["agentId"]: r.get("attr") for r in mapped.get("agents") or []}
        local = {a.get("name"): a for a in structure["agents"]}
        registered = [
            {
                **a,
                "file": (local.get(a.get("name")) or {}).get("file"),
                "attr": attrs.get((local.get(a.get("name")) or {}).get("id")),
            }
            for a in connected.get("registered") or []
        ]
        connect_live_traffic(console, root, server, key, registered)
    else:
        # Connected, but nothing to show: saying "your agents are set up" here was false.
        console.print(
            "[yellow]●[/yellow] Connected, but no agents were found, so there is nothing "
            "to set up yet. Fix that (see below), then run this again."
        )
    if structure["agents"] and structure["tools"]:
        # Found what it was looking for: the full list of shapes would bury the result.
        console.print(
            "[dim]Missing an agent or tool? What mapping recognises: "
            "https://useagentfox.com/docs/discover — then run this again.[/dim]\n"
        )
    else:
        _print_missing_help(console)
    return mapped


def _poll_forever(
    api: Any, console: Console, root: Path, mapped: dict[str, Any], structure: dict[str, Any]
) -> None:
    """Stay connected, and run each attack test the dashboard starts."""
    agents: dict[tuple[str, str], Any] = {}
    try:
        while True:
            try:
                reply = api.post(
                    "/runner/poll", {"project": mapped.get("project"), "protocol": PROTOCOL}
                )
                if reply.get("needStructure"):
                    api.post(
                        "/runner/connect",
                        {"structure": structure, "project": mapped.get("project")},
                    )
            except ApiError as exc:
                if exc.status in (401, 403):
                    console.print(f"[red]AgentFox stopped accepting this setup key:[/red] {exc}")
                    raise SystemExit(1) from exc
                console.print(f"[yellow]Lost touch with AgentFox ({exc}); retrying…[/yellow]")
                time.sleep(POLL_SECONDS * 2)
                continue
            except (httpx.HTTPError, RuntimeError) as exc:
                console.print(f"[yellow]Lost touch with AgentFox ({exc}); retrying…[/yellow]")
                time.sleep(POLL_SECONDS * 2)
                continue
            job = reply.get("job")
            if job:
                _run_job(console, api, root, mapped, job, agents)
            time.sleep(POLL_SECONDS)
    except KeyboardInterrupt:
        console.print("\nStopped. Run the same command again to reconnect.")


def connect_live_traffic(
    console: Console,
    root: Path,
    server: str,
    key: str,
    registered: list[dict[str, Any]],
    *,
    ask: bool | None = None,
) -> Path | None:
    """Make the app's own calls show up in AgentFox: save the workspace key where
    `agentfox.auto()` finds it, and add that one line to the file that starts the
    agent. Returns the file changed, if any.

    The key goes to ``.agentfox/agentfox.env`` (owner-only, git-ignored). The line is
    added only with the user's yes, asked when there is a terminal to ask in;
    otherwise it is printed for them to add.
    """
    import sys

    from agentfox.capabilities.onboarding.project_files import insert_auto, write_env
    from agentfox.platform.identity.operators import API_KEY_PREFIX

    if not key.startswith(API_KEY_PREFIX):
        return None  # an older setup key cannot send traffic
    write_env(
        root, {"AGENTFOX_URL": server.rstrip("/"), "AGENTFOX_API_KEY": key}, by="agentfox init"
    )

    entry = _entry_file(root, registered)
    if entry is None:
        console.print(
            "[dim]Saved your key in .agentfox/agentfox.env. To see your app's calls, add "
            "`import agentfox; agentfox.auto()` where it starts.[/dim]"
        )
        return None
    path, slug = entry
    rel = path.relative_to(root)
    block = f'import agentfox\n\nagentfox.auto("{slug}")  # added by `agentfox init`\n'
    if "agentfox.auto(" in path.read_text(errors="ignore"):
        console.print(
            f"[green]●[/green] {rel} already calls agentfox.auto(): its calls show up live."
        )
        return None
    if ask is None:
        ask = sys.stdin.isatty()
    answer = "n"
    if ask:
        try:
            answer = (
                console.input(
                    f"  Add one line to [cyan]{rel}[/cyan] so your app's calls show up in "
                    "AgentFox? [bold]\\[Y/n][/bold] "
                )
                .strip()
                .lower()
                or "y"
            )
        except EOFError:
            answer = "n"
    if answer.startswith("y"):
        insert_auto(path, block)
        console.print(
            f'[green]●[/green] {rel} now calls agentfox.auto("{slug}"). Run your app as usual: '
            "its calls show up under Activity."
        )
        return path
    console.print(
        f"[dim]To see your app's calls, add to {rel}:[/dim]\n"
        f'    import agentfox; agentfox.auto("{slug}")'
    )
    return None


def _entry_file(root: Path, registered: list[dict[str, Any]]) -> tuple[Path, str] | None:
    """The Python file that defines (and, best, runs) an agent, and that agent's slug."""
    from agentfox.capabilities.onboarding.project_files import _MAIN_GUARD

    candidates = [
        (root / a["file"], a["slug"], a.get("attr"))
        for a in registered
        if (a.get("file") or "").endswith(".py") and (root / a["file"]).is_file()
    ]
    if not candidates:
        return None

    def rank(candidate: tuple[Path, str, str | None]) -> tuple[bool, bool]:
        """The agent the file runs comes first: named under `if __name__ == "__main__"`."""
        text = candidate[0].read_text(errors="ignore")
        guard = _MAIN_GUARD.search(text)
        name = candidate[2]
        runs = bool(guard and name and re.search(rf"\b{re.escape(name)}\b", text[guard.end() :]))
        return (not runs, not guard)

    path, slug, _attr = sorted(candidates, key=rank)[0]
    return path, slug


def _print_coverage(console: Console, mapped: dict[str, Any]) -> None:
    """What was read, and what may have been missed because of it."""
    from agentfox.capabilities.discovery.repo import SUPPORTED_LANGUAGES

    s = mapped["structure"]
    n_agents, n_tools = len(s["agents"]), len(s["tools"])
    n_handoffs = sum(len(a.get("handsOffTo") or []) for a in s["agents"])
    read = mapped.get("read", 0)
    console.print(
        f"[bold]Recognised[/bold]: {n_agents} agent{'s' if n_agents != 1 else ''}, "
        f"{n_tools} tool{'s' if n_tools != 1 else ''}"
        + (f", {n_handoffs} hand-off{'s' if n_handoffs != 1 else ''}" if n_handoffs else "")
        + f" [dim]from {read} code file{'s' if read != 1 else ''}"
        + (f" ({', '.join(mapped['frameworks'])})" if mapped.get("frameworks") else "")
        + "[/dim]"
    )
    unreadable = mapped.get("unreadable") or []
    if unreadable:
        shown = ", ".join(unreadable[:5]) + (" …" if len(unreadable) > 5 else "")
        console.print(
            f"[yellow]Couldn't read {len(unreadable)} file(s)[/yellow] [dim]({shown})[/dim]"
        )
    # Nothing here in a language the scan reads: "found nothing" would be a guess.
    if not read:
        skipped = mapped.get("skipped_summary") or ""
        # The summary can itself be a sentence ("no other files were present").
        rest = (
            f"this folder has {skipped}"
            if skipped and not skipped.startswith("no ")
            else "this folder has nothing else"
        )
        console.print(
            f"[yellow]Read no source:[/yellow] init reads {SUPPORTED_LANGUAGES}; [dim]{rest}.[/dim]"
        )
    loose = mapped.get("unassigned_tools") or []
    if loose:
        console.print(
            f"[yellow]Tools found but not given to any agent:[/yellow] {', '.join(loose)} "
            "[dim](pass them in the agent's tools=[...] to include them)[/dim]"
        )
    console.print()


def _print_missing_help(console: Console) -> None:
    """How to add an agent, tool or model that init did not find."""
    from agentfox.capabilities.discovery.platforms import RECOGNISED as HOSTED
    from agentfox.capabilities.onboarding.mapper import RECOGNISED

    found = "".join(f"  • {what}: [cyan]{shapes}[/cyan]\n" for what, shapes in RECOGNISED)
    found += (
        "  • Agents configured on a hosted platform, from the files the repository keeps "
        f"for them: [cyan]{', '.join(what for what, _ in HOSTED)}[/cyan]\n"
    )
    console.print(
        "\n[bold]Missing something?[/bold] Mapping reads your code; it never runs it. "
        "The attack test does run your agent, here on this machine, with every tool "
        "faked so nothing real happens. Mapping finds:\n"
        + found
        + "  If an agent or tool isn't listed above: give the agent a [cyan]name=[/cyan], pass the "
        "tool in its [cyan]tools=[...][/cyan], set [cyan]model=[/cyan] where it's created, then "
        "run this same command again.\n"
        "  Running it again adds what's new and keeps the guardrails you already have.\n"
        "  Already found but not allowed? In AgentFox, open the agent → Limits and access.\n"
    )


def _print_map(console: Console, structure: dict[str, Any]) -> None:
    systems = {s["id"]: s["name"] for s in structure["systems"]}
    for agent in structure["agents"]:
        sure = {
            "medium": "  [yellow]likely an agent[/yellow]",
            "low": "  [yellow]possible agent[/yellow]",
        }
        note = sure.get(agent.get("confidence", "high"), "")
        if agent.get("system"):
            # A crew, team or swarm runs its members; it has no model of its own.
            names = {a["id"]: a["name"] for a in structure["agents"]}
            members = ", ".join(names.get(i, i) for i in agent.get("handsOffTo") or [])
            console.print(f"[bold]{agent['name']}[/bold]  [dim]system: runs {members}[/dim]")
            if not any(t["agentId"] == agent["id"] for t in structure["tools"]):
                console.print()
                continue
        else:
            console.print(f"[bold]{agent['name']}[/bold]  [dim]{agent['model']}[/dim]{note}")
        if note and agent.get("evidence"):
            console.print(f"  [dim]found by: {agent['evidence']}[/dim]")
        table = Table(show_header=True, header_style="dim", box=None, padding=(0, 2))
        table.add_column("tool")
        table.add_column("can")
        table.add_column("touches", style="dim")
        for t in structure["tools"]:
            if t["agentId"] == agent["id"]:
                table.add_row(
                    t["name"], RISK_LABEL[t["risk"]], systems.get(t.get("systemId", ""), "")
                )
        console.print(table)
        console.print()


def agent_ref(agent: dict[str, Any], mapped: dict[str, Any]) -> tuple[str, str, str | None] | None:
    """(module, attribute, kind) of the live object for a structure agent: from the
    structure (discovery's ``module``/``attr``/``attrKind``, or a ``ref``), else from
    what this machine's mapping found for the same agent id."""
    ref = agent.get("ref") if isinstance(agent.get("ref"), dict) else None
    if ref and ref.get("module") and (ref.get("attr") or ref.get("name")):
        return ref["module"], ref.get("attr") or ref["name"], ref.get("kind")
    if agent.get("module") and agent.get("attr"):
        return agent["module"], agent["attr"], agent.get("attrKind")
    for r in mapped.get("agents") or []:
        if r.get("agentId") == agent.get("id") and r.get("module") and r.get("attr"):
            return r["module"], r["attr"], r.get("kind") or r.get("attrKind")
    return None


def _drivers(
    console: Console,
    root: Path,
    mapped: dict[str, Any],
    structure: dict[str, Any],
    loaded: dict[tuple[str, str], Any],
) -> dict[str, Any]:
    """One driver per agent in the map, each loading that agent's own object."""
    from agentfox.capabilities.onboarding.runner import (
        Driver,
        error_text,
        load_agent,
        make_driver,
        user_modules,
    )

    out: dict[str, Any] = {}
    for agent in structure.get("agents") or []:
        name = agent.get("name") or "agent"
        ref = agent_ref(agent, mapped)
        if ref is None:
            out[agent["id"]] = Driver(
                name,
                refuse=f"Not run: AgentFox couldn't find where {name} is created "
                "(a module-level `agent = ...`, or a function that builds or runs it).",
            )
            continue
        module, attr, kind = ref
        try:
            if (module, attr) not in loaded:
                loaded[(module, attr)] = load_agent(root, module, attr)
        except Exception as exc:  # noqa: BLE001 - their import failing is the answer
            # Said once here; its attacks' identical "not run" lines aren't printed.
            hint = (
                "install your agent's dependencies in this environment (the one running "
                "agentfox init)"
                if isinstance(exc, ImportError)
                else "check that it imports on its own"
            )
            console.print(
                f"[red]Couldn't load {module}.{attr}[/red] ({error_text(exc)}), so {name}'s "
                f"attacks won't run. To fix it, {hint}, then run the test again."
            )
            out[agent["id"]] = Driver(
                name, refuse=f"Not run: couldn't load {module}.{attr}: {error_text(exc)}"
            )
            continue
        tools = [t for t in structure.get("tools") or [] if t.get("agentId") == agent["id"]]
        out[agent["id"]] = make_driver(
            loaded[(module, attr)],
            name=name,
            kind=kind,
            framework=agent.get("framework"),
            tools=tools,
            modules=user_modules(root),
        )
    return out


def _guards(api: _Api, run_id: str, structure: dict[str, Any], drivers: dict[str, Any]) -> dict:
    """Each agent's check against its real policies (an "after" test). An agent the
    registry doesn't know has no policies to test: it isn't run."""
    from agentfox.capabilities.onboarding.runner import Driver, Verdict

    path = f"/runner/runs/{run_id}/guard"
    guards: dict[str, Any] = {}
    for agent in structure.get("agents") or []:
        slug = agent.get("slug")
        if not slug:
            name = agent.get("name") or "agent"
            drivers[agent["id"]] = Driver(
                name,
                refuse=f"Not run: {name} isn't in AgentFox's registry, so it has no "
                "guardrails to test.",
            )
            continue

        def guard(surface: str, payload: dict[str, Any], slug: str = slug) -> Verdict:
            return Verdict.from_json(api.post(path, {"agent": slug, "surface": surface, **payload}))

        guards[agent["id"]] = guard
    return guards


def _run_job(
    console: Console,
    api: _Api,
    root: Path,
    mapped: dict[str, Any],
    job: dict[str, Any],
    loaded: dict[tuple[str, str], Any],
) -> None:
    from agentfox.capabilities.onboarding.runner import explain_model_error, run_suite

    run_id, phase = job["runId"], job["phase"]
    structure = job.get("structure") or mapped["structure"]
    checked = bool(job.get("policies")) or phase == "after"
    label = "with your guardrails" if checked else "without guardrails"
    suite = build_suite(structure, job.get("sets"))
    console.print(
        f"[bold]Running {suite_size(suite)} {label}[/bold] · tools are faked, nothing real happens"
    )
    out = _Results(api, run_id)
    drivers = _drivers(console, root, mapped, structure, loaded)
    guards = _guards(api, run_id, structure, drivers) if checked else None
    # An agent that won't run at all: its reason once, not once per attack (they are
    # still reported to the server, each with the reason).
    refused: dict[str, int] = {}
    for a in suite:
        d = drivers.get(a.agent_id)
        if d is not None and d.refuse and not a.skip:
            refused[d.refuse] = refused.get(d.refuse, 0) + 1
    for reason, n in refused.items():
        if "couldn't load" not in reason:  # already said, with how to fix it
            console.print(f"  {TAGS['not_run']}  {reason} ({n} attack{'s' if n != 1 else ''})")

    lock = threading.Lock()
    stats = {"done": 0, "through": 0, "ran": 0}
    errors: list[str] = []
    stop = threading.Event()

    def pump() -> None:
        while not stop.wait(BATCH_SECONDS):
            out.tick()  # a failed report stays queued and goes with the next one

    def on_result(r: dict[str, Any]) -> None:
        out.add(r)
        with lock:
            stats["done"] += 1
            stats["through"] += int(r.get("outcome") == "got_through")
            if r.get("outcome") != "not_run":
                stats["ran"] += 1
                if r.get("error"):
                    errors.append(r["error"])
        if r.get("outcome") == "not_run" and r.get("reason") in refused:
            return
        tag = TAGS.get(r.get("outcome", ""), "")
        console.print(f"  {stats['done']:>3}/{len(suite)}  {tag}  {r['sentence']}")

    # If the first attacks all fail the same way, the model is unreachable (no
    # credits, bad key): stop, and say so once, instead of failing every attack.
    def broken() -> bool:
        with lock:
            seen = stats["ran"]
            first = list(errors)
        return (
            seen >= FAIL_FAST
            and len(first) >= FAIL_FAST
            and stats["through"] == 0
            and seen == len(first)
        )

    pumper = threading.Thread(target=pump, daemon=True)
    pumper.start()
    try:
        run_suite(
            drivers,
            suite,
            structure,
            on_result,
            guards=guards,
            should_stop=lambda: out.closed or broken(),
            root=root,
        )
    finally:
        stop.set()
        pumper.join()
    if out.closed:
        console.print("\n[yellow]AgentFox ended this test before it finished.[/yellow]\n")
        return
    if broken():
        message = explain_model_error(errors[0])
        out.finish(error=message)
        console.print(f"\n[red]Stopped:[/red] {message}\n")
        return
    if not out.finish():
        console.print(
            "\n[red]Couldn't send the last results to AgentFox.[/red] "
            "Check the connection, then run the test again.\n"
        )
        return
    if stats["ran"] == 0:
        console.print(
            "\n[red]No attack could be run[/red], so this test says nothing about your agent "
            "yet. The reason is above.\n"
        )
        return
    console.print(
        f"\n[bold]{stats['through']} attacks got through.[/bold] Results are on your screen.\n"
    )
