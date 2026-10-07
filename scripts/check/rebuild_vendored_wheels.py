#!/usr/bin/env python3
"""Pre-commit hook: keep the vendored wheels honest.

`api/` and `demo/redteam-live-lang/` both deploy `agentfox` from a prebuilt wheel
checked into their own `vendor/` directory, not an editable install — see
docs/architecture/high-level-design.md's deployment-shape section for why. That makes
the wheel a second copy of the package that a commit can update `src/agentfox/`
without touching, and nothing before this hook noticed when that happened. It already
happened twice on 2026-09-04: the demo
crashed in production on a schema change its wheel never picked up, and
`guardrails-api` served week-old code for long enough that a completely new route
returned 404 in production.

So: any commit whose staged changes touch `src/agentfox/` rebuilds both vendored
wheels and stages the result, the same way a formatter rewrites and re-stages a
file. If the build itself fails, the commit is blocked — better here than after
`git push` triggers a deploy.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
VENDOR_DIRS = ["api/vendor", "demo/redteam-live-lang/vendor"]


def staged_files() -> list[str]:
    out = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout.splitlines()


def main() -> int:
    if not any(f.startswith("src/agentfox/") for f in staged_files()):
        return 0

    print("src/agentfox/ changed — rebuilding vendored wheels so they can't drift...")
    for vendor_dir in VENDOR_DIRS:
        out_dir = REPO_ROOT / vendor_dir
        if not out_dir.is_dir():
            continue
        result = subprocess.run(
            ["uv", "build", "--wheel", "--out-dir", str(out_dir)],
            cwd=REPO_ROOT,
        )
        if result.returncode != 0:
            print(f"wheel build for {vendor_dir} failed — commit blocked.", file=sys.stderr)
            return 1
        subprocess.run(["git", "add", vendor_dir], cwd=REPO_ROOT, check=True)
        print(f"  {vendor_dir}: rebuilt and staged")

    return 0


if __name__ == "__main__":
    sys.exit(main())
