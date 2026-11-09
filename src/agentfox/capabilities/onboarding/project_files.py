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

#: File names that usually start a program.
ENTRY_NAMES = ("main.py", "app.py", "server.py", "agent.py", "run.py", "__main__.py", "cli.py")

#: A line that runs an agent rather than defining one: the call that starts the loop,
#: per framework. A file holding one is where `auto()` has to run first.
AGENT_RUN = re.compile(
    r"""
      \bRunner\.run(?:_sync|_streamed)?\s*\(          # OpenAI Agents SDK
    | \.kickoff(?:_async|_for_each(?:_async)?)?\s*\(   # CrewAI crews and flows
    | \.a?invoke\s*\(|\.a?stream\s*\(                  # LangChain runnables, LangGraph graphs
    | \binitiate_chat\s*\(|\.run_stream\s*\(           # AutoGen
    | \b(?:agent|runner|executor|team|crew|graph|app)\.run(?:_sync|_async)?\s*\(
    """,
    re.X,
)

#: Directories an entry point is never in.
_NOT_ENTRY_DIRS = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "env",
        "node_modules",
        "__pycache__",
        "site-packages",
        "dist",
        "build",
        "docs",
        "tests",
        "test",
        "testing",
        "fixtures",
        "mocks",
    }
)
#: How far below the project root an entry point is looked for (src/pkg/sub/main.py).
_ENTRY_DEPTH = 5
_ENTRY_MAX_FILES = 4000


def _declared_entries(root: Path) -> set[str]:
    """Files the project itself says start it, as dotted modules or relative paths:
    `[project.scripts]` (and Poetry's scripts) in pyproject.toml, and the graphs a
    LangGraph server loads from langgraph.json."""
    declared: set[str] = set()
    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        import tomllib

        try:
            data = tomllib.loads(pyproject.read_text(errors="ignore"))
        except (OSError, tomllib.TOMLDecodeError):
            data = {}
        scripts = dict((data.get("project") or {}).get("scripts") or {})
        scripts |= ((data.get("tool") or {}).get("poetry") or {}).get("scripts") or {}
        for target in scripts.values():
            if isinstance(target, str) and ":" in target:
                declared.add(target.split(":", 1)[0].strip())
    graphs_file = root / "langgraph.json"
    if graphs_file.is_file():
        import json

        try:
            graphs = json.loads(graphs_file.read_text(errors="ignore")).get("graphs") or {}
        except (OSError, ValueError, AttributeError):
            graphs = {}
        for spec in graphs.values() if isinstance(graphs, dict) else ():
            if isinstance(spec, str) and ":" in spec:
                declared.add(spec.rsplit(":", 1)[0].strip())
    return declared


def _matches_declared(rel: str, declared: set[str]) -> bool:
    path = Path(rel)
    as_module = ".".join(path.with_suffix("").parts)
    package = ".".join(path.parent.parts) if path.name in ("__init__.py", "__main__.py") else None
    for entry in declared:
        if entry.endswith(".py") or "/" in entry:
            if Path(os.path.normpath(entry)) == path:
                return True
            continue
        # `pkg.main` names src/pkg/main.py, pkg/main.py or lib/x/pkg/main.py.
        if as_module == entry or as_module.endswith("." + entry):
            return True
        if package and (package == entry or package.endswith("." + entry)):
            return True
    return False


def entry_points(
    root: Path,
    *,
    model_call_files: dict[str, int] | None = None,
    agent_files: frozenset[str] | set[str] = frozenset(),
) -> list[Path]:
    """The Python files that start the agent, best guess first.

    What counts, strongest first: a file the project declares as its entry point
    (`[project.scripts]`, langgraph.json), a file that runs an agent (Runner.run,
    crew.kickoff(), graph.invoke() …) or runs as a script (``__main__``), a file named
    like an entry point; ties go to the file with more model calls, then the one
    nearer the root. Tests, docs and virtualenvs are never candidates. Read, never
    imported."""
    from agentfox.capabilities.discovery.agents import is_test_path

    calls = dict(model_call_files or {})
    declared = _declared_entries(root)
    root = Path(root)
    scored: list[tuple[tuple[int, int, int, str], Path]] = []
    seen = 0
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = os.path.relpath(dirpath, root)
        depth = 0 if rel_dir == "." else rel_dir.count(os.sep) + 1
        dirnames[:] = sorted(
            d
            for d in dirnames
            if d not in _NOT_ENTRY_DIRS and not d.startswith(".") and depth < _ENTRY_DEPTH
        )
        for filename in sorted(filenames):
            if not filename.endswith(".py"):
                continue
            seen += 1
            if seen > _ENTRY_MAX_FILES:
                break
            rel = os.path.normpath(os.path.join(rel_dir, filename))
            if is_test_path(rel):
                continue
            path = root / rel
            try:
                text = path.read_text(errors="ignore")
            except OSError:
                continue
            score = 0
            if _matches_declared(rel, declared):
                score += 4
            if _MAIN_GUARD.search(text):
                score += 2
            if AGENT_RUN.search(text):
                score += 2
            if filename in ENTRY_NAMES:
                score += 1
            if rel in agent_files:
                score += 1
            n_calls = calls.get(rel, 0)
            # A file that only defines things and is named nothing special is not an
            # entry point, however many model calls it holds, unless nothing else is.
            if score < 2 and not n_calls:
                continue
            scored.append(((score, n_calls, -depth, rel), path))
    scored.sort(key=lambda item: (-item[0][0], -item[0][1], -item[0][2], item[0][3]))
    return [path for _key, path in scored]


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


def write_env(root: Path, values: dict[str, str], *, by: str = "agentfox up") -> Path:
    """Merge ``values`` into the env file, readable by this user only, and keep it out
    of git when this is a repository. ``by`` names the command writing it, for its
    header: `agentfox init`, `agentfox up` and `agentfox login` all do."""
    directory = root / STATE_DIR
    directory.mkdir(exist_ok=True)
    path = directory / ENV_FILE
    merged = {**read_env(root), **{k: v for k, v in values.items() if v}}
    body = [
        f"# Written by `{by}`. Holds credentials: never commit it.",
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
