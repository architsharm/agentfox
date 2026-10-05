#!/usr/bin/env python3
"""Drift checker for the AgentFox harness.

Fails (exit 1) when the harness markdown has drifted from the product:
  * an `agentfox <group> <command> --flag` in any harness .md that the real CLI rejects
  * a repo-relative path in backticks or a markdown link that does not exist
  * a skill / command / agent file missing its required frontmatter
  * a repo .md file that reference/docs-map.md does not classify

Run from the repo root inside the project venv:  uv run python harness/scripts/check_harness.py
"""

from __future__ import annotations

import fnmatch
import re
import subprocess
import sys
from pathlib import Path

HARNESS = Path(__file__).resolve().parents[1]
REPO = HARNESS.parent
sys.path.insert(0, str(REPO / "src"))

try:
    import click
    import typer.main

    from agentfox.cli.main import app
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
# `nometria` is still accepted: the console script keeps that name as an alias, so a
# stale invocation in the markdown must still be validated rather than silently skipped.
INVOCATION = re.compile(
    r"(?<![\w./\[-])(?:agentfox|nometria)(?:\.sh)?[ \t]+([a-z][a-z-]*(?:[ \t]+[^\s`|]+)*)"
)
FLAG = re.compile(r"(?<![\w-])(--?[a-zA-Z][\w-]*)")
NOT_COMMANDS = {"import", "is", "the", "cli", "control", "harness", "does", "starts", "must", "and"}


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
    # A default-command group (`scan`, `serve`, `report` — see cli/layout.py) hands
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
    r"^(?:src|docs|tests|scripts|benchmarks|deploy|dashboard|demo|migrations|api|harness)/[\w./*-]+$"
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
            if not (REPO / span).exists() and not (HARNESS / span).exists():
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


def check_frontmatter(md: Path, text: str) -> None:
    rel = md.relative_to(HARNESS).parts
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
    docs_map = (HARNESS / "reference" / "docs-map.md").read_text()
    patterns = [p for p in CODE_SPAN.findall(docs_map) if p.endswith(".md")]
    tracked = subprocess.run(
        ["git", "ls-files", "*.md"], cwd=REPO, capture_output=True, text=True, check=False
    ).stdout.split()
    for rel in tracked:
        if rel.startswith("harness/") or rel.startswith(".claude"):
            continue
        if not any(fnmatch.fnmatch(rel, pat) for pat in patterns):
            errors.append(f"harness/reference/docs-map.md: repo doc `{rel}` is not classified")


def main() -> int:
    files = sorted(HARNESS.rglob("*.md"))
    for md in files:
        text = md.read_text()
        check_invocation(md, text)
        if md.name == "cli.md" and md.parent.name == "reference":
            cli_md_rows(md, text)
        check_paths(md, text)
        check_frontmatter(md, text)
    check_docs_map()
    if errors:
        print(f"harness drift: {len(errors)} problem(s)")
        for e in sorted(set(errors)):
            print("  -", e)
        return 1
    print(f"harness OK: {len(files)} markdown files checked against the live CLI and repo")
    return 0


if __name__ == "__main__":
    sys.exit(main())
