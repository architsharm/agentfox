"""What `agentfox up` knows before it asks anything.

Every question the wizard asks has a default, and the defaults come from here: what
the scan found, which coding agents this project uses, whether Docker is on the path,
where the git remote points, and what the person answered last time. The point is
that pressing Enter through every question gives the right setup for this repository.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agentfox.capabilities.discovery.machine import MachineReport
    from agentfox.capabilities.discovery.repo import ScanReport

#: Where `up` keeps what it needs between runs. `.agentfox/` already holds a project's
#: own policy packs (`.agentfox/policies/`).
STATE_DIR = ".agentfox"
ANSWERS_FILE = "up.json"
#: Secrets (API token, database password) and the environment the integrations read.
#: Written 0600 and kept out of git.
ENV_FILE = "agentfox.env"


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "agent"


@dataclass
class Harness:
    name: str  # adapter name: "claude", "codex"
    display: str
    present: bool  # this project or this machine uses it
    hooked: list[str] = field(default_factory=list)  # agents its hooks already govern


@dataclass
class Context:
    root: Path
    report: ScanReport
    harnesses: list[Harness]
    entry_points: list[Path]
    github_repo: str | None
    docker: bool
    saved: dict[str, Any]
    #: The AI tools set up on this machine (`agentfox scan machine`), or None when skipped.
    machine: MachineReport | None = None
    #: The repository's own SKILL.md files, as `agentfox scan skills` reports them.
    skills: list[dict[str, Any]] = field(default_factory=list)

    @property
    def project(self) -> str:
        return slugify(self.root.resolve().name)

    @property
    def python_calls(self) -> int:
        return sum(1 for s in self.report.model_calls if s.file.endswith(".py"))

    @property
    def other_calls(self) -> int:
        return len(self.report.model_calls) - self.python_calls

    @property
    def tool_names(self) -> list[str]:
        names = {s.name for s in self.report.tools if s.name}
        return sorted(names)

    @property
    def mcp_names(self) -> list[str]:
        return sorted({s.name for s in self.report.mcp_servers if s.name})


def _on_path(binary: str) -> bool:
    return shutil.which(binary) is not None


#: `agentfox scan machine`'s client names, for the harnesses that have an adapter.
_MACHINE_CLIENTS = {"Claude Code": "claude", "Codex": "codex"}


def _harnesses(root: Path, machine: MachineReport | None) -> list[Harness]:
    from agentfox import harnesses

    # Signs a project uses a coding agent: its config directory or instructions file
    # in the repo, the binary on this machine, or its user-level config, as the
    # machine scan found it.
    signs = {
        "claude": (root / ".claude", root / "CLAUDE.md"),
        "codex": (root / ".codex", root / "AGENTS.md"),
    }
    configured = {
        _MACHINE_CLIENTS[c["client"]]
        for c in (machine.configs if machine else [])
        if c["client"] in _MACHINE_CLIENTS
    }
    found = []
    for adapter in harnesses.all():
        present = (
            any(p.exists() for p in signs.get(adapter.name, ()))
            or _on_path(adapter.name)
            or adapter.name in configured
        )
        try:
            hooked = sorted(adapter.hooked_agents(root))
        except Exception:  # an unreadable settings file is not a reason to stop
            hooked = []
        found.append(Harness(adapter.name, adapter.display_name, present or bool(hooked), hooked))
    return found


_MAIN_GUARD = re.compile(r"""^if __name__ == ["']__main__["']""", re.M)
_ENTRY_NAMES = ("main.py", "app.py", "server.py", "agent.py", "run.py", "__main__.py")


def _entry_points(root: Path, report: ScanReport) -> list[Path]:
    """Python files that start the agent, best guess first: files with model calls
    that are also run as a script or named like an entry point."""
    scored: dict[Path, int] = {}
    for site in report.model_calls:
        if not site.file.endswith(".py"):
            continue
        path = root / site.file
        scored[path] = scored.get(path, 0) + 1
    for name in _ENTRY_NAMES:
        for path in root.glob(f"*/{name}"):
            scored.setdefault(path, 0)
        if (root / name).is_file():
            scored.setdefault(root / name, 0)

    def score(path: Path) -> tuple[int, int, str]:
        try:
            text = path.read_text(errors="ignore")
        except OSError:
            return (0, 0, str(path))
        runs = 2 if _MAIN_GUARD.search(text) else 0
        named = 1 if path.name in _ENTRY_NAMES else 0
        return (runs + named, scored[path], str(path))

    ranked = sorted((p for p in scored if p.is_file()), key=score, reverse=True)
    # A file nobody runs and that makes no model call is not an entry point.
    return [p for p in ranked if score(p)[0] or scored[p]][:5]


_REMOTE = re.compile(r"github\.com[:/]([^/\s]+)/([^/\s]+?)(?:\.git)?/?$")


def github_repo(root: Path) -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    match = _REMOTE.search(out.stdout.strip())
    return f"{match.group(1)}/{match.group(2)}" if match else None


def load_answers(root: Path) -> dict[str, Any]:
    path = root / STATE_DIR / ANSWERS_FILE
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def save_answers(root: Path, answers: dict[str, Any]) -> Path:
    directory = root / STATE_DIR
    directory.mkdir(exist_ok=True)
    path = directory / ANSWERS_FILE
    path.write_text(json.dumps(answers, indent=2, sort_keys=True) + "\n")
    return path


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


def detect(root: Path, *, machine: bool = True) -> Context:
    """Everything `up` knows before it asks: the repository scan, the repository's
    skills and, unless ``machine`` is off, the AI tools set up on this machine."""
    from agentfox.capabilities.discovery.machine import scan_machine
    from agentfox.capabilities.discovery.repo import scan
    from agentfox.capabilities.discovery.skills import scan_skills_dir

    report = scan(root)
    machine_report = scan_machine() if machine else None
    return Context(
        root=root,
        report=report,
        harnesses=_harnesses(root, machine_report),
        entry_points=_entry_points(root, report),
        github_repo=github_repo(root),
        docker=_on_path("docker"),
        saved=load_answers(root),
        machine=machine_report,
        skills=scan_skills_dir(root),
    )
