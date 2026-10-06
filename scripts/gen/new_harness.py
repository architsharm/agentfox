"""Scaffold a coding-agent harness adapter from `scripts/templates/harness/`.

    uv run python scripts/gen/new_harness.py codex [--display-name "Codex CLI"]

Writes `src/agentfox/harnesses/<module>/` (adapter skeleton, package init, a fixtures
README) and prints the remaining steps. It does not register the adapter: an adapter is
registered once its captured fixtures pass the conformance suite, because registering it
is what puts it in front of every hook call.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TEMPLATE = REPO / "scripts" / "templates" / "harness"
HARNESSES = REPO / "src" / "agentfox" / "harnesses"


def render(text: str, values: dict[str, str]) -> str:
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", value)
    return text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("name", help="the --harness name hooks will use, e.g. codex or gemini-cli")
    parser.add_argument("--display-name", help="the product name, for people")
    args = parser.parse_args(argv)

    name = args.name.strip().lower()
    if not re.fullmatch(r"[a-z][a-z0-9-]*", name):
        print(f"harness name {name!r}: use lowercase letters, digits and dashes", file=sys.stderr)
        return 2
    module = name.replace("-", "_")
    values = {
        "name": name,
        "module": module,
        "display_name": args.display_name or name.replace("-", " ").title(),
        "class_name": "".join(part.title() for part in module.split("_")) + "Adapter",
    }
    target = HARNESSES / module
    if target.exists():
        print(f"{target.relative_to(REPO)} already exists; nothing written", file=sys.stderr)
        return 1

    for source in sorted(TEMPLATE.rglob("*.tmpl")):
        dest = target / source.relative_to(TEMPLATE).with_suffix("")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(render(source.read_text(), values))
        print(f"wrote {dest.relative_to(REPO)}")

    print(
        f"""
Next:
  1. Capture real {values["display_name"]} hook payloads into {target.relative_to(REPO)}/fixtures/
     (one <kind>.json and <kind>.expected.json per event; see the README there).
  2. Implement parse, render and install in adapter.py, and fill EVENTS, CAPABILITIES,
     TOOL_MAP and TOOL_IMPACTS from what the probe showed.
  3. Register it: add `{name} = "agentfox.harnesses.{module}:ADAPTER"` under
     [project.entry-points."agentfox.harnesses"] in pyproject.toml and to BUILTIN in
     src/agentfox/harnesses/__init__.py, then run
     `uv run pytest tests/harnesses/conformance.py`."""
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
