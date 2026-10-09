#!/usr/bin/env python3
"""Drift checker for the AgentFox operator plugins (`plugins/`).

`plugins/shared/` holds the runtime-neutral parts (AGENTS.md, skills/, reference/). A
runtime plugin such as `plugins/claude-code/` carries committed copies of them, because a
Claude Code plugin cannot load files outside its own directory once installed. This
script makes those copies (`--write`) and fails when they drift.

Fails (exit 1) when:
  * a runtime plugin's copy of a shared file differs from `plugins/shared/`
  * an `agentfox <group> <command> --flag` in any plugin .md that the real CLI rejects
  * a repo-relative path in backticks or a markdown link that does not exist
  * a skill / command / agent file missing its required frontmatter
  * a repo .md file that plugins/shared/reference/docs-map.md does not classify

Run from the repo root inside the project venv:
  uv run python scripts/check/plugins.py            # check
  uv run python scripts/check/plugins.py --write    # refresh the copies, then check
"""

from __future__ import annotations

import argparse
import filecmp
import fnmatch
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PLUGINS = REPO / "plugins"
SHARED = PLUGINS / "shared"
#: What `shared/` provides, copied verbatim into every runtime plugin below.
SHARED_PARTS = ("AGENTS.md", "skills", "reference", "scripts")
#: The runtime plugins that carry a copy of the shared parts.
RUNTIMES = ("claude-code", "codex")
sys.path.insert(0, str(REPO / "src"))

try:
    import click
    import typer.main

    from agentfox.apps.cli.main import app
except Exception as exc:  # pragma: no cover - environment problem, not drift
    print(
        f"cannot import the agentfox CLI ({exc}). "
        f"Run inside the project venv: uv run python {__file__}"
    )
    sys.exit(2)

ROOT_CMD: click.Group = typer.main.get_command(app)  # type: ignore[assignment]
errors: list[str] = []


def err(path: Path, msg: str) -> None:
    errors.append(f"{path.relative_to(REPO)}: {msg}")


# ---------------------------------------------------------------- CLI references
CODE_SPAN = re.compile(r"`([^`\n]+)`")
INVOCATION = re.compile(r"(?<![\w./\[-])agentfox(?:\.sh)?[ \t]+([a-z][a-z-]*(?:[ \t]+[^\s`|]+)*)")
FLAG = re.compile(r"(?<![\w-])(--?[a-zA-Z][\w-]*)")
NOT_COMMANDS = {
    "import",
    "is",
    "the",
    "cli",
    "control",
    "harness",
    "plugin",
    "does",
    "starts",
    "must",
    "and",
}


def resolve(words: list[str]) -> tuple[click.Command | None, str]:
    cmd: click.Command = ROOT_CMD
    path = ["agentfox"]
    for word in words:
        if not isinstance(cmd, click.Group):
            break
        if word.startswith("-") or not re.fullmatch(r"[a-z][a-z-]*", word):
            break
        sub = cmd.get_command(click.Context(cmd), word)
        if sub is None:
            return None, " ".join(path + [word])
        cmd, path = sub, path + [word]
    if isinstance(cmd, click.Group) and cmd is not ROOT_CMD:
        # a bare group reference ("the `agents` group") is fine
        return cmd, " ".join(path)
    return cmd, " ".join(path)


def known_flags(cmd: click.Command) -> set[str]:
    flags = {"--help"}
    for p in cmd.params:
        flags.update(getattr(p, "opts", []))
        flags.update(getattr(p, "secondary_opts", []))
    # A default-command group (`scan`, `serve`, `report` — see apps/cli/layout.py) hands
    # unknown words to its default subcommand, and routes some flags to another one
    # (`scan --sessions`), so their flags are the group's too.
    if isinstance(cmd, click.Group) and getattr(cmd, "default_command", None):
        targets = [cmd.default_command, *getattr(cmd, "flag_routes", {}).values()]
        flags.update(getattr(cmd, "flag_routes", {}))
        for name in targets:
            sub = cmd.commands.get(name)
            if sub is not None:
                flags |= known_flags(sub)
    return flags


FENCE = re.compile(r"^```[^\n]*\n(.*?)^```", re.S | re.M)


def code_fragments(text: str) -> list[str]:
    """Inline code spans and fenced-block lines, skipping lines that say a command doesn't exist."""
    frags: list[str] = []
    for block in FENCE.findall(text):
        frags.extend(block.splitlines())
    prose = FENCE.sub("", text)
    for line in prose.splitlines():
        if "does not exist" in line or "doesn't exist" in line:
            continue  # known-issues quotes phantom commands on purpose
        frags.extend(CODE_SPAN.findall(line))
    return frags


def check_invocation(md: Path, text: str) -> None:
    for frag in code_fragments(text):
        _check_fragment(md, frag)


def _check_fragment(md: Path, text: str) -> None:
    for m in INVOCATION.finditer(text):
        tail = m.group(1)
        words = tail.split()
        if not words or words[0] in NOT_COMMANDS:
            continue
        cmd, name = resolve(words)
        if cmd is None:
            err(md, f"unknown command `{name}`")
            continue
        if cmd is ROOT_CMD:
            continue
        allowed = known_flags(cmd)
        for flag in FLAG.findall(tail):
            for part in flag.split("/"):
                if part.startswith("-") and part not in allowed:
                    err(md, f"`{name}` has no option `{part}`")


def cli_md_rows(md: Path, text: str) -> None:
    """reference/cli.md tables list commands without the `agentfox ` prefix."""
    for line in text.splitlines():
        if not line.startswith("| `"):
            continue
        first_cell = line.split("|")[1]
        for span in CODE_SPAN.findall(first_cell):
            spec = span if span.startswith(("agentfox", "agentfox")) else "agentfox " + span
            _check_fragment(md, spec)


# ---------------------------------------------------------------- paths and links
LINK = re.compile(r"\]\(([^)#\s]+)(?:#[^)]*)?\)")
REPO_PATH = re.compile(
    r"^(?:src|docs|tests|scripts|benchmarks|deploy|dashboard|demo|migrations|api|plugins)/[\w./*-]+$"
)


def check_paths(md: Path, text: str) -> None:
    for target in LINK.findall(text):
        if re.match(r"^[a-z]+://", target):
            continue
        if not (md.parent / target).resolve().exists():
            err(md, f"broken link `{target}`")
    for span in CODE_SPAN.findall(text):
        span = span.strip().rstrip(".,:")
        if REPO_PATH.match(span) and "*" not in span and "<" not in span:
            # A path may be repo-relative, or relative to a plugin root: shared files
            # name the launcher as `scripts/agentfox.sh`, which each runtime plugin has.
            roots = [REPO, plugin_root(md), *(PLUGINS / r for r in RUNTIMES)]
            if not any((root / span).exists() for root in roots):
                err(md, f"path `{span}` does not exist")


# ---------------------------------------------------------------- frontmatter
def frontmatter(text: str) -> dict[str, str]:
    if not text.startswith("---\n"):
        return {}
    block = text[4 : text.find("\n---", 4)]
    out: dict[str, str] = {}
    for line in block.splitlines():
        if ":" in line and not line.startswith(" "):
            key, _, value = line.partition(":")
            out[key.strip()] = value.strip()
    return out


REQUIRED = {
    "skills": ("name", "description"),
    "commands": ("description",),
    "agents": ("name", "description", "tools"),
    "reference": ("title", "layer", "source_of_truth", "verified_against"),
}


def plugin_root(md: Path) -> Path:
    """`plugins/<name>/` for a file inside one, else `plugins/`."""
    rel = md.relative_to(PLUGINS).parts
    return PLUGINS / rel[0] if len(rel) > 1 else PLUGINS


def check_frontmatter(md: Path, text: str) -> None:
    rel = md.relative_to(plugin_root(md)).parts
    kind = rel[0] if len(rel) > 1 else None
    if kind == "skills" and md.name != "SKILL.md":
        return
    if kind not in REQUIRED:
        return
    fm = frontmatter(text)
    for key in REQUIRED[kind]:
        if not fm.get(key):
            err(md, f"missing frontmatter `{key}`")
    if kind == "skills" and fm.get("name") != md.parent.name:
        err(md, f"skill name `{fm.get('name')}` must equal folder name `{md.parent.name}`")


# ---------------------------------------------------------------- docs map coverage
def check_docs_map() -> None:
    docs_map = (SHARED / "reference" / "docs-map.md").read_text()
    patterns = [p for p in CODE_SPAN.findall(docs_map) if p.endswith(".md")]
    tracked = subprocess.run(
        ["git", "ls-files", "*.md"], cwd=REPO, capture_output=True, text=True, check=False
    ).stdout.split()
    for rel in tracked:
        if rel.startswith("plugins/") or rel.startswith(".claude"):
            continue
        if not any(fnmatch.fnmatch(rel, pat) for pat in patterns):
            errors.append(
                f"plugins/shared/reference/docs-map.md: repo doc `{rel}` is not classified"
            )


# ---------------------------------------------------------------- shared copies
def _files(root: Path) -> set[Path]:
    """Every file under ``root`` (or ``root`` itself), relative to its parent."""
    if root.is_file():
        return {Path(root.name)}
    if not root.exists():
        return set()
    return {p.relative_to(root.parent) for p in root.rglob("*") if p.is_file()}


def write_copies() -> None:
    for runtime in RUNTIMES:
        target = PLUGINS / runtime
        for part in SHARED_PARTS:
            dest = target / part
            if dest.is_dir():
                shutil.rmtree(dest)
            elif dest.exists():
                dest.unlink()
            source = SHARED / part
            if source.is_dir():
                shutil.copytree(source, dest)
            else:
                shutil.copy2(source, dest)


def check_copies() -> None:
    for runtime in RUNTIMES:
        target = PLUGINS / runtime
        expected: set[Path] = set()
        actual: set[Path] = set()
        for part in SHARED_PARTS:
            expected |= _files(SHARED / part)
            actual |= _files(target / part)
        hint = "edit plugins/shared/ and run `python scripts/check/plugins.py --write`"
        for rel in sorted(expected - actual):
            errors.append(f"plugins/{runtime}/{rel}: missing copy of plugins/shared/{rel} ({hint})")
        for rel in sorted(actual - expected):
            errors.append(f"plugins/{runtime}/{rel}: not in plugins/shared/ ({hint})")
        for rel in sorted(expected & actual):
            if not filecmp.cmp(SHARED / rel, target / rel, shallow=False):
                errors.append(
                    f"plugins/{runtime}/{rel}: differs from plugins/shared/{rel} ({hint})"
                )


def is_copy(md: Path) -> bool:
    rel = md.relative_to(PLUGINS).parts
    return len(rel) > 1 and rel[0] in RUNTIMES and rel[1] in SHARED_PARTS


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--write", action="store_true", help="refresh the runtime plugins' copies of shared/"
    )
    args = parser.parse_args()
    if args.write:
        write_copies()
    check_copies()
    # The copies are byte-identical to shared/ (checked above), so they are not checked twice.
    files = sorted(md for md in PLUGINS.rglob("*.md") if not is_copy(md))
    for md in files:
        text = md.read_text()
        check_invocation(md, text)
        if md.name == "cli.md" and md.parent.name == "reference":
            cli_md_rows(md, text)
        check_paths(md, text)
        check_frontmatter(md, text)
    check_docs_map()
    if errors:
        print(f"plugin drift: {len(errors)} problem(s)")
        for e in sorted(set(errors)):
            print("  -", e)
        return 1
    print(
        f"plugins OK: {len(files)} markdown files checked against the live CLI and repo; "
        f"copies of plugins/shared/ match in {', '.join(RUNTIMES)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
