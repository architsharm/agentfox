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
#: This many errors and nothing else, from the first attacks, means the model is unreachable.
FAIL_FAST = 6
RISK_LABEL = {
    "high": "[red]can do real damage[/red]",
    "outside": "[yellow]talks to the outside[/yellow]",
    "read_only": "[dim]read only[/dim]",
}


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
            raise RuntimeError(f"{res.status_code}: {detail}")
        return res.json()


def connect(key: str, server: str, path: str | Path = ".", console: Console | None = None) -> None:
    console = console or Console()
    root = Path(path).resolve()
    api = _Api(server, key)

    console.print(f"\n[bold]AgentFox[/bold] · mapping [cyan]{root.name}[/cyan]\n")
    mapped = map_repository(root)
    structure = mapped["structure"]
    _print_map(console, structure)
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
    console.print(
        "[dim]Keep this running: it runs the attack tests on this machine when you start "
        "them. Ctrl-C to stop.[/dim]\n"
    )

    agent = None
    try:
        while True:
            try:
                reply = api.post("/runner/poll")
            except (httpx.HTTPError, RuntimeError) as exc:
                console.print(f"[yellow]Lost touch with AgentFox ({exc}); retrying…[/yellow]")
                time.sleep(POLL_SECONDS * 2)
                continue
            if reply.get("needStructure"):
                api.post(
                    "/runner/connect", {"structure": structure, "project": mapped.get("project")}
                )
            job = reply.get("job")
            if job:
                agent = _run_job(console, api, root, mapped, job, agent)
            time.sleep(POLL_SECONDS)
    except KeyboardInterrupt:
        console.print("\nStopped. Run the same command again to reconnect.")


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
    console.print(
        f"[bold]Running 140 attacks {label}[/bold] · tools are faked, nothing real happens"
    )
    ref = next((a for a in mapped["agents"] if a.get("module") and a.get("attr")), None)
    if ref is None:
        api.post(
            f"/runner/runs/{run_id}/results",
            {
                "error": "Couldn't find the agent object to run "
                "(a module-level `agent = create_agent(...)`)."
            },
        )
        return agent
    try:
        if agent is None:
            agent, _tools = load_agent(root, ref["module"], ref["attr"])
    except Exception as exc:
        api.post(
            f"/runner/runs/{run_id}/results",
            {"error": f"Couldn't load {ref['module']}.{ref['attr']}: {exc}"},
        )
        console.print(f"[red]Couldn't load your agent:[/red] {exc}")
        return None

    suite = build_suite(structure)
    pending: list[dict[str, Any]] = []
    lock = threading.Lock()
    stats = {"done": 0, "through": 0}
    errors: list[str] = []
    stop = threading.Event()

    def flush(done: bool = False) -> None:
        with lock:
            batch = list(pending)
            pending.clear()
        if batch or done:
            api.post(f"/runner/runs/{run_id}/results", {"results": batch, "done": done})

    def pump() -> None:
        while not stop.wait(BATCH_SECONDS):
            try:
                flush()
            except Exception:  # the next flush retries what it can
                pass

    def on_result(r: dict[str, Any]) -> None:
        with lock:
            pending.append(r)
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
            should_stop=broken,
        )
    finally:
        stop.set()
        pumper.join()
    if broken():
        message = explain_model_error(errors[0])
        flush()
        api.post(f"/runner/runs/{run_id}/results", {"error": message})
        console.print(f"\n[red]Stopped:[/red] {message}\n")
        return agent
    flush(done=True)
    console.print(
        f"\n[bold]{stats['through']} of {len(suite)} attacks got through.[/bold] "
        "Results are on your screen.\n"
    )
    return agent
