"""Map every fetched repository with `agentfox init`'s mapper.

Writes <work_dir>/maps/<repo>.json and <work_dir>/map_report.json, the inputs to
run_latency.py, run_concurrency.py and report.py.

Usage: python -m benchmarks.latency.map_repos <repos_dir> <work_dir>
"""

from __future__ import annotations

import csv
import json
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures import TimeoutError as Timeout
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
#: The demo agents shipped in this repository, mapped where they are.
IN_TREE = {
    "redteam-live": REPO / "demo" / "redteam-live",
    "redteam-live-lang": REPO / "demo" / "redteam-live-lang",
}


def one(path: str) -> dict:
    from agentfox.capabilities.onboarding.mapper import map_repository

    t = time.perf_counter()
    mapped = map_repository(Path(path))
    return {"mapped": mapped, "secs": round(time.perf_counter() - t, 1)}


def git(path: Path, *args: str) -> str:
    out = subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=True)
    return out.stdout.strip()


def main() -> None:
    repos, work = Path(sys.argv[1]), Path(sys.argv[2])
    maps = work / "maps"
    maps.mkdir(parents=True, exist_ok=True)
    listed = {r["repo"]: r for r in csv.DictReader(open(HERE / "results" / "01_repos.csv"))}
    targets = {p.name: p for p in sorted(repos.iterdir()) if p.is_dir()}
    targets.update(IN_TREE)
    report: dict[str, dict] = {}
    with ProcessPoolExecutor(4) as ex:
        futs = {name: ex.submit(one, str(p)) for name, p in targets.items()}
        for name, fut in futs.items():
            row = listed.get(name, {})
            entry = {
                "source": row.get("source", "public"),
                "url": row.get("url") or git(targets[name], "remote", "get-url", "origin"),
                "commit": git(targets[name], "rev-parse", "--short", "HEAD") or "-",
            }
            try:
                res = fut.result(timeout=900)
                s = res["mapped"]["structure"]
                (maps / f"{name}.json").write_text(json.dumps(res["mapped"], default=str))
                entry.update(
                    agents=len(s["agents"]), tools=len(s.get("tools", [])), map_s=res["secs"]
                )
                if not s["agents"]:
                    entry["note"] = "0 agents found by the mapper"
            except Timeout:
                entry.update(agents=0, note="mapping took over 15 min; skipped")
            except Exception as e:  # a repository the mapper cannot read is reported, not fatal
                entry.update(agents=0, note=f"mapper error: {str(e)[:120]}")
            report[name] = entry
            print(
                f"{name:32} agents={entry.get('agents')} tools={entry.get('tools', 0)}", flush=True
            )
    (work / "map_report.json").write_text(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
