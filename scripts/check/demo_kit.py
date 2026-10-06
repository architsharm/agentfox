#!/usr/bin/env python3
"""Drift checker for the red-team demos' shared kit (`demo/kit/`).

`demo/kit/` is the one implementation of the support-tools agent, its seed and its
verification, shared by both live demos. The LangChain demo (`demo/redteam-live-lang/`)
deploys on Vercel with that folder as the project's Root Directory, so nothing outside
it exists at deploy time: it carries a committed copy at `demo/redteam-live-lang/kit/`.
This script makes that copy (`--write`) and fails when it drifts, the same pattern as
`plugins/shared/` -> `plugins/claude-code/` (scripts/check_plugins.py).

Fails (exit 1) when a copy is missing a kit file, has a file the kit does not, or has
a file whose bytes differ. Needs nothing but the standard library.

  python scripts/check/demo_kit.py            # check
  python scripts/check/demo_kit.py --write    # refresh the copies, then check
"""

from __future__ import annotations

import argparse
import filecmp
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
KIT = REPO / "demo" / "kit"
#: Deployed demos that cannot see `demo/kit/` and so carry a copy of it.
COPIES = (REPO / "demo" / "redteam-live-lang" / "kit",)
#: Never part of the kit: interpreter and tool caches.
IGNORED_PARTS = {"__pycache__", ".ruff_cache", ".pytest_cache"}
HINT = "edit demo/kit/ and run `python scripts/check/demo_kit.py --write`"


def _files(root: Path) -> set[Path]:
    if not root.is_dir():
        return set()
    return {
        p.relative_to(root)
        for p in root.rglob("*")
        if p.is_file()
        and not IGNORED_PARTS.intersection(p.relative_to(root).parts)
        and p.suffix not in {".pyc", ".pyo"}
    }


def write_copies() -> None:
    for dest in COPIES:
        if dest.exists():
            shutil.rmtree(dest)
        dest.mkdir(parents=True)
        for rel in sorted(_files(KIT)):
            (dest / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(KIT / rel, dest / rel)


def check_copies() -> list[str]:
    errors: list[str] = []
    expected = _files(KIT)
    if not expected:
        return [f"{KIT.relative_to(REPO)}: the kit is missing or empty"]
    for dest in COPIES:
        name = dest.relative_to(REPO).as_posix()
        actual = _files(dest)
        for rel in sorted(expected - actual):
            errors.append(f"{name}/{rel.as_posix()}: missing copy of demo/kit/{rel} ({HINT})")
        for rel in sorted(actual - expected):
            errors.append(f"{name}/{rel.as_posix()}: not in demo/kit/ ({HINT})")
        for rel in sorted(expected & actual):
            if not filecmp.cmp(KIT / rel, dest / rel, shallow=False):
                errors.append(f"{name}/{rel.as_posix()}: differs from demo/kit/{rel} ({HINT})")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--write", action="store_true", help="refresh the copies of demo/kit/")
    args = parser.parse_args()
    if args.write:
        write_copies()
    errors = check_copies()
    if errors:
        print(f"demo kit drift: {len(errors)} problem(s)")
        for e in errors:
            print("  -", e)
        return 1
    copies = ", ".join(d.relative_to(REPO).as_posix() for d in COPIES)
    print(f"demo kit OK: {len(_files(KIT))} files in demo/kit/ match their copy in {copies}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
