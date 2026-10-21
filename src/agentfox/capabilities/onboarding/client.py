"""`agentfox init --key`: map this repo, report it, then stay connected and run
the onboarding's attack tests when the dashboard asks for them.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

import httpx
from rich.console import Console
from rich.table import Table

from agentfox.capabilities.onboarding.attacks import build_suite
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
        res = self.http.post(f"/api/onboarding{path}", json=body or {})
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
    console = console or Console()
    root = Path(path).resolve()
    api = _Api(server, key)

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
        api.post("/runner/connect", {"structure": structure, "project": mapped.get("project")})
    except (httpx.HTTPError, RuntimeError) as exc:
        console.print(f"[red]Couldn't reach AgentFox at {server}:[/red] {exc}")
        raise SystemExit(1) from exc
    console.print("[green]●[/green] Connected. Your agents are set up: open AgentFox to see them.")
    _print_missing_help(console)
    console.print(
        "[dim]Keep this running: it runs the attack tests on this machine when you start "
        "them. Ctrl-C to stop.[/dim]\n"
    )

    agent = None
    try:
        while True:
            try:
                reply = api.post("/runner/poll", {"project": mapped.get("project")})
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
                agent = _run_job(console, api, root, mapped, job, agent)
            time.sleep(POLL_SECONDS)
    except KeyboardInterrupt:
        console.print("\nStopped. Run the same command again to reconnect.")


def _print_coverage(console: Console, mapped: dict[str, Any]) -> None:
    """What was read, and what may have been missed because of it."""
    s = mapped["structure"]
    n_agents, n_tools = len(s["agents"]), len(s["tools"])
    console.print(
        f"[bold]Recognised[/bold]: {n_agents} agent{'s' if n_agents != 1 else ''}, "
        f"{n_tools} tool{'s' if n_tools != 1 else ''} "
        f"[dim]from {mapped.get('read', 0)} Python files[/dim]"
    )
    unreadable = mapped.get("unreadable") or []
    if unreadable:
        shown = ", ".join(unreadable[:5]) + (" …" if len(unreadable) > 5 else "")
        console.print(
            f"[yellow]Couldn't read {len(unreadable)} file(s)[/yellow] [dim]({shown})[/dim]"
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
    console.print(
        "\n[bold]Missing something?[/bold] init reads your code; it never runs it. It finds:\n"
        "  • LangChain / LangGraph: [cyan]@tool[/cyan] functions and "
        "[cyan]create_agent(model=..., tools=[...])[/cyan]\n"
        "  • OpenAI Agents SDK: [cyan]@function_tool[/cyan] / [cyan]function_tool(fn)[/cyan] and "
        "[cyan]Agent(name=..., model=..., tools=[...], handoffs=[...])[/cyan]\n"
        "  • Plain function calling: [cyan]chat.completions.create(tools=[...])[/cyan] "
        "with JSON tool schemas\n"
        "  If an agent or tool isn't listed above: give the agent a [cyan]name=[/cyan], pass the "
        "tool in its [cyan]tools=[...][/cyan], set [cyan]model=[/cyan] where it's created, then "
        "run this same command again.\n"
        "  Running it again adds what's new and keeps the guardrails you already have.\n"
        "  Already found but not allowed? In AgentFox, open the agent → Limits and access.\n"
    )


def _print_map(console: Console, structure: dict[str, Any]) -> None:
    systems = {s["id"]: s["name"] for s in structure["systems"]}
    for agent in structure["agents"]:
        console.print(f"[bold]{agent['name']}[/bold]  [dim]{agent['model']}[/dim]")
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


def _run_job(
    console: Console, api: _Api, root: Path, mapped: dict[str, Any], job: dict[str, Any], agent: Any
) -> Any:
    from agentfox.capabilities.onboarding.runner import explain_model_error, load_agent, run_suite

    run_id, phase = job["runId"], job["phase"]
    structure = job.get("structure") or mapped["structure"]
    label = "with your guardrails" if phase == "after" else "without guardrails"
    suite = build_suite(structure, job.get("sets"))
    console.print(
        f"[bold]Running {len(suite)} attacks {label}[/bold] · tools are faked, nothing real happens"
    )
    out = _Results(api, run_id)
    ref = next((a for a in mapped["agents"] if a.get("module") and a.get("attr")), None)
    if ref is None:
        out.finish(
            error="Couldn't find the agent object to run "
            "(a module-level `agent = create_agent(...)`)."
        )
        return agent
    try:
        if agent is None:
            agent, _tools = load_agent(root, ref["module"], ref["attr"])
    except Exception as exc:
        out.finish(error=f"Couldn't load {ref['module']}.{ref['attr']}: {exc}")
        console.print(f"[red]Couldn't load your agent:[/red] {exc}")
        return None

    lock = threading.Lock()
    stats = {"done": 0, "through": 0}
    errors: list[str] = []
    stop = threading.Event()

    def pump() -> None:
        while not stop.wait(BATCH_SECONDS):
            out.tick()  # a failed report stays queued and goes with the next one

    def on_result(r: dict[str, Any]) -> None:
        out.add(r)
        with lock:
            stats["done"] += 1
            stats["through"] += int(bool(r.get("gotThrough")))
            if r.get("error"):
                errors.append(r["error"])
        tag = (
            "[red]GOT THROUGH[/red]"
            if r.get("gotThrough")
            else "[yellow]ERROR[/yellow]"
            if r.get("error")
            else "[green]RESISTED[/green]"
        )
        console.print(f"  {stats['done']:>3}/{len(suite)}  {tag}  {r['sentence']}")

    # If the first attacks all fail the same way, the model is unreachable (no
    # credits, bad key): stop, and say so once, instead of failing 140 times.
    def broken() -> bool:
        with lock:
            seen = stats["done"]
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
            agent,
            suite,
            structure,
            job.get("guardrails") or [],
            on_result,
            agent_name=structure["agents"][0]["name"],
            should_stop=lambda: out.closed or broken(),
        )
    finally:
        stop.set()
        pumper.join()
    if out.closed:
        console.print("\n[yellow]AgentFox ended this test before it finished.[/yellow]\n")
        return agent
    if broken():
        message = explain_model_error(errors[0])
        out.finish(error=message)
        console.print(f"\n[red]Stopped:[/red] {message}\n")
        return agent
    if not out.finish():
        console.print(
            "\n[red]Couldn't send the last results to AgentFox.[/red] "
            "Check the connection, then run the test again.\n"
        )
        return agent
    console.print(
        f"\n[bold]{stats['through']} of {len(suite)} attacks got through.[/bold] "
        "Results are on your screen.\n"
    )
    return agent
