"""Files `agentfox` writes into a project: the env file holding its key, the line
that adds `agentfox.auto()`, and how the file that runs an agent is recognised.

Shared by `agentfox up` (the CLI wizard) and `agentfox init` (the onboarding
runner), which is why they live here and not in either.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

#: Where `up` keeps what it needs between runs. `.agentfox/` already holds a project's
#: own policy packs (`.agentfox/policies/`).
STATE_DIR = ".agentfox"
#: Secrets (API token, database password) and the environment the integrations read.
#: Written 0600 and kept out of git.
ENV_FILE = "agentfox.env"

_MAIN_GUARD = re.compile(r"""^if __name__ == ["']__main__["']""", re.M)
_AUTO_MARK = "agentfox.auto("


def read_env(root: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        lines = (root / STATE_DIR / ENV_FILE).read_text().splitlines()
    except OSError:
        return values
    for line in lines:
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip().strip('"')
    return values


def write_env(root: Path, values: dict[str, str]) -> Path:
    """Merge ``values`` into the env file, readable by this user only, and keep it out
    of git when this is a repository."""
    directory = root / STATE_DIR
    directory.mkdir(exist_ok=True)
    path = directory / ENV_FILE
    merged = {**read_env(root), **{k: v for k, v in values.items() if v}}
    body = [
        "# Written by `agentfox up`. Holds credentials: never commit it.",
        "# Load it with:  set -a; . .agentfox/agentfox.env; set +a",
        *(f"{key}={value}" for key, value in sorted(merged.items())),
    ]
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as handle:
        handle.write("\n".join(body) + "\n")
    os.chmod(path, 0o600)
    git_ignore(root, f"{STATE_DIR}/{ENV_FILE}")
    return path


def git_ignore(root: Path, entry: str) -> None:
    """Add ``entry`` to the project's .gitignore, when the project is a git repository."""
    if not (root / ".git").exists():
        return
    gitignore = root / ".gitignore"
    existing = gitignore.read_text() if gitignore.is_file() else ""
    if entry in existing.split():
        return
    prefix = "" if not existing or existing.endswith("\n") else "\n"
    gitignore.write_text(f"{existing}{prefix}{entry}\n")


def insert_auto(path: Path, block: str) -> bool:
    """Put ``block`` after the module docstring and ``from __future__`` imports, before
    the model clients are imported. False when the file already calls auto()."""
    text = path.read_text()
    if _AUTO_MARK in text:
        return False
    import ast

    lines = text.splitlines(keepends=True)
    at = 0
    try:
        module = ast.parse(text)
    except SyntaxError:
        module = None
    if module is not None:
        for node in module.body:
            docstring = (
                isinstance(node, ast.Expr)
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
                and node is module.body[0]
            )
            future = isinstance(node, ast.ImportFrom) and node.module == "__future__"
            if docstring or future:
                at = node.end_lineno or at
            else:
                break
    elif lines and lines[0].startswith("#!"):
        at = 1
    head, tail = "".join(lines[:at]), "".join(lines[at:]).lstrip("\n")
    if head and not head.endswith("\n"):
        head += "\n"
    path.write_text(f"{head}\n{block}\n{tail}" if head else f"{block}\n{tail}")
    return True
