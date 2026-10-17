"""Run the scenarios in scenarios.json and print every turn as JSON.

    .venv/bin/python run_all.py                    # all of them
    .venv/bin/python run_all.py competitor seat    # just these

The cancellation-with-approval scenario waits for a person, so it has its own script:
approval_flow.py.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from drive import converse

SCENARIOS: dict[str, dict[str, Any]] = json.loads(
    (Path(__file__).parent / "scenarios.json").read_text()
)


async def run(names: list[str]) -> dict[str, list[dict[str, Any]]]:
    unknown = [n for n in names if n not in SCENARIOS]
    if unknown:
        raise SystemExit(f"unknown scenario(s): {', '.join(unknown)}; see scenarios.json")
    return {name: await converse(SCENARIOS[name]["turns"]) for name in names}


if __name__ == "__main__":
    names = sys.argv[1:] or list(SCENARIOS)
    print(json.dumps(asyncio.run(run(names)), indent=1, default=str))
