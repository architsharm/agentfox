"""Clone the public repositories the latency benchmark used, at the commits it used.

Reads results/01_repos.csv. The study's private projects are not published and are
skipped; the two demo agents in this repository are mapped in place by map_repos.py.

Usage: python -m benchmarks.latency.fetch_repos <repos_dir>
"""

from __future__ import annotations

import csv
import subprocess
import sys
from pathlib import Path

RESULTS = Path(__file__).resolve().parent / "results"


def main() -> None:
    dest = Path(sys.argv[1])
    dest.mkdir(parents=True, exist_ok=True)
    for row in csv.DictReader(open(RESULTS / "01_repos.csv")):
        if not row["source"].startswith("public") or not row["url"].startswith("http"):
            continue
        path = dest / row["repo"]
        if not path.exists():
            subprocess.run(
                ["git", "clone", "-q", "--filter=blob:none", row["url"], str(path)], check=False
            )
        if row["commit"] not in ("", "-") and path.exists():
            subprocess.run(["git", "-C", str(path), "checkout", "-q", row["commit"]], check=False)
        print(row["repo"], row["commit"], flush=True)


if __name__ == "__main__":
    main()
