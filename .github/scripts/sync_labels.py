#!/usr/bin/env python3
"""Apply `.github/labels.yml` to the repository's labels.

    GH_TOKEN=... REPO=owner/name python3 .github/scripts/sync_labels.py [--dry-run]

Run by `.github/workflows/labels.yml` on every push to main that touches the
manifest, and by hand with `--dry-run` to see what a run would change.

Additive on purpose. It creates labels that are missing and corrects the colour
and description of labels the manifest names. It never deletes one: deleting a
label strips it from every issue carrying it, with no undo, and this repository's
labels are also applied by issue forms and by Dependabot.

Colours are spelled `colour` in the manifest to match the rest of the repository
and converted here, because the GitHub API field is `color`.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote

import yaml

MANIFEST = Path(__file__).resolve().parents[1] / "labels.yml"
HEX = re.compile(r"^[0-9a-f]{6}$")


def gh_api(path: str, *, method: str = "GET", fields: dict | None = None) -> object:
    """One `gh api` call. Raises with the response body when GitHub refuses."""
    cmd = ["gh", "api", "-X", method, path]
    if method == "GET":
        cmd += ["--paginate"]
    for key, value in (fields or {}).items():
        cmd += ["-f", f"{key}={value}"]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise SystemExit(f"{method} {path} failed:\n{proc.stderr.strip()}")
    if not proc.stdout.strip():
        return None
    # --paginate concatenates JSON arrays, so join them back into one list.
    chunks = [json.loads(c) for c in re.split(r"(?<=\])\s*(?=\[)", proc.stdout.strip())]
    if chunks and isinstance(chunks[0], list):
        return [item for chunk in chunks for item in chunk]
    return chunks[0]


def main() -> int:
    dry_run = "--dry-run" in sys.argv
    repo = os.environ.get("REPO") or os.environ.get("GITHUB_REPOSITORY")
    if not repo:
        raise SystemExit("set REPO=owner/name (or GITHUB_REPOSITORY)")

    wanted = yaml.safe_load(MANIFEST.read_text())["labels"]
    for entry in wanted:
        colour = str(entry["colour"]).lstrip("#").lower()
        if not HEX.match(colour):
            raise SystemExit(f"{entry['name']}: colour {entry['colour']!r} is not six hex digits")
        entry["colour"] = colour

    existing = {label["name"]: label for label in gh_api(f"repos/{repo}/labels")}
    created, updated, unchanged = [], [], []

    for entry in wanted:
        name, colour, description = entry["name"], entry["colour"], entry["description"]
        current = existing.get(name)
        if current is None:
            created.append(name)
            if not dry_run:
                gh_api(
                    f"repos/{repo}/labels",
                    method="POST",
                    fields={"name": name, "color": colour, "description": description},
                )
        elif (
            current["color"].lower() != colour or (current.get("description") or "") != description
        ):
            updated.append(name)
            if not dry_run:
                # The name goes in the path, so a label whose name changed in the
                # manifest is created fresh rather than renamed. That is the safe
                # direction: nothing loses its label.
                gh_api(
                    f"repos/{repo}/labels/{quote(name, safe='')}",
                    method="PATCH",
                    fields={"new_name": name, "color": colour, "description": description},
                )
        else:
            unchanged.append(name)

    verb = "would create" if dry_run else "created"
    print(f"{verb}: {', '.join(created) or 'nothing'}")
    print(f"{'would update' if dry_run else 'updated'}: {', '.join(updated) or 'nothing'}")
    print(f"unchanged: {len(unchanged)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
