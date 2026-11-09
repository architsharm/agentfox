"""What `agentfox up` knows before it asks anything.

Every question the wizard asks has a default, and the defaults come from here: what
the scan found, which coding agents this project uses, whether Docker is on the path,
where the git remote points, and what the person answered last time. The point is
that pressing Enter through every question gives the right setup for this repository.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agentfox.capabilities.onboarding.project_files import (  # noqa: F401 - re-exported
    _MAIN_GUARD,
    ENTRY_NAMES,
    ENV_FILE,
    STATE_DIR,
    git_ignore,
    read_env,
    write_env,
)

if TYPE_CHECKING:
    from agentfox.capabilities.discovery.machine import MachineReport
    from agentfox.capabilities.discovery.repo import ScanReport

ANSWERS_FILE = "up.json"


def slugify(text: str) -> str:
    """The registry key for a name (:func:`agentfox.core.naming.slug`): what `up`
    writes into `auto("...")` is what `init`, the scan and the registry call it."""
    from agentfox.core.naming import slug

    return slug(text)


@dataclass
class Harness:
    name: str  # adapter name: "claude", "codex"
    display: str
    present: bool  # this project or this machine uses it
    hooked: list[str] = field(default_factory=list)  # agents its hooks already govern
    #: This repository is set up for it (its config directory or instructions file),
    #: not only this machine.
    in_repo: bool = False


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
    def git_root(self) -> Path | None:
        return git_root(self.root)

    @property
    def is_agent_project(self) -> bool:
        """The repository holds an agent or model calls of its own, as opposed to being
        a codebase someone works on with a coding agent."""
        return bool(self.report.agents or self.report.model_calls)

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
    def agent_tools(self) -> dict[str, str]:
        """Tool name -> the agent it runs, for each agent another uses as a tool
        (``as_tool`` edges whose tool name the scan could read)."""
        return {
            e.tool: e.child for e in self.report.agent_edges if e.relation == "as_tool" and e.tool
        }

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
        in_repo = any(p.exists() for p in signs.get(adapter.name, ()))
        found.append(
            Harness(
                adapter.name, adapter.display_name, present or bool(hooked), hooked, in_repo=in_repo
            )
        )
    return found


def git_root(root: Path) -> Path | None:
    """The top of the git repository ``root`` is in (``.git`` a directory or, in a
    worktree or submodule, a file), or None outside one. Read from the filesystem: no
    git binary needed."""
    here = root.resolve()
    for candidate in (here, *here.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def _entry_points(root: Path, report: ScanReport) -> list[Path]:
    """Python files that start the agent, best guess first (see `entry_points`): the
    files the project declares, runs as a script or runs an agent from, anywhere
    under src/ or a package, not only at the top."""
    from agentfox.capabilities.onboarding.project_files import entry_points

    calls: dict[str, int] = {}
    for site in report.model_calls:
        if site.file.endswith(".py"):
            calls[site.file] = calls.get(site.file, 0) + 1
    agents = {a.file for a in report.agents if a.file.endswith(".py")}
    return entry_points(root, model_call_files=calls, agent_files=agents)[:5]


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
