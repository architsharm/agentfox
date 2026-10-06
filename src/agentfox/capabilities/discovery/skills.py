"""Agent skills, scanned the way MCP servers already are.

A skill is a `SKILL.md`: YAML frontmatter naming it, a prose body the model
follows, and often a directory of scripts beside it. Structurally it is the
same object as an MCP tool — a description the model reads to decide whether to
invoke it, and instructions it then obeys — so it inherits the same attack, and
`scan_mcp_server`'s `tool_poisoning` check applies almost verbatim.

It arrived as a category in 2026: OWASP published an Agentic Skills Top 10, and
a vendor analysing 206,435 real skills reported every one of the ten occurring
in the wild. We scanned MCP servers and not skills, which is the same supply
chain one layer up.

What this does NOT do, stated here rather than discovered later:

  * **No drift detection.** `scan_mcp_server` can say "these tools changed
    under us" because it stores a digest per snapshot. Doing that for skills
    needs its own table, and a rug-pull check that silently never fires would
    be worse than an absent one. The digest is returned so a caller can store
    it; nothing here compares.
  * **No sandbox.** Scripts beside a skill are reported as present and
    unmentioned, never read or run.
  * **Prose is prose.** A skill that describes its dangerous behaviour in
    ordinary English, with no directive phrasing and no code block, is not
    caught. This finds planted instructions and declared commands, not intent.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from agentfox.capabilities.detection.actions import analyse_shell

#: Directive shapes in a skill's description or body. The same list
#: `registry.service` uses on MCP tool descriptions, plus two that only make
#: sense in a document long enough to have sections — a skill body is prose,
#: an MCP description is a sentence.
_PLANTED_DIRECTIVE = [
    re.compile(r"\b(?:ignore|disregard)\s+(?:all\s+)?(?:previous|prior)\b", re.I),
    re.compile(r"\byou\s+must\s+(?:always|first|before)\b", re.I),
    re.compile(r"\b(?:do\s+not|don'?t|never)\s+(?:tell|inform|mention\s+to)\s+the\s+user\b", re.I),
    re.compile(r"<\s*(?:system|important|instructions?)\s*>", re.I),
    re.compile(
        r"\bbefore\s+(?:using|calling)\s+this\s+(?:tool|skill),?\s+(?:you\s+)?(?:must|should)\b",
        re.I,
    ),
    # Skill-specific: telling the model to keep the skill's own behaviour from
    # the operator, or to treat the skill as outranking its instructions.
    re.compile(
        r"\b(?:without|do\s+not\s+(?:ask|request))\s+(?:asking\s+)?(?:for\s+)?"
        r"(?:permission|confirmation|approval)\b",
        re.I,
    ),
    re.compile(
        r"\bthis\s+(?:skill|document)\s+(?:overrides|supersedes|takes\s+precedence)\b", re.I
    ),
]

#: Fenced code, so a command declared in a skill can go through the same
#: analyser a command the agent actually runs would.
_FENCE = re.compile(r"```(?:[\w.-]*)\n(.*?)```", re.S)

#: Shells worth extracting. A ```python block is a script, not a command line,
#: and running the shell deny-list over Python is how false positives happen.
_SHELL_FENCE = re.compile(r"```(?:sh|bash|zsh|shell|console|terminal)?\n(.*?)```", re.S)

#: Files beside a skill that are code rather than documentation.
_EXECUTABLE_SUFFIXES = {".sh", ".bash", ".zsh", ".py", ".js", ".ts", ".rb", ".pl", ".ps1", ".exe"}

#: Tool grants in frontmatter that are not a grant at all.
_WILDCARD = re.compile(r"[*]|\ball\b", re.I)


def _issue(kind: str, severity: str, **detail: Any) -> dict[str, Any]:
    return {"type": kind, "severity": severity, **detail}


def analyse_skill(
    *,
    name: str,
    body: str,
    frontmatter: dict[str, Any] | None = None,
    sibling_files: list[str] | None = None,
) -> dict[str, Any]:
    """Hygiene issues in one skill. Pure — no session, no filesystem, no network.

    Separated from the walker below so the checks can be tested against a
    string, and so a caller holding skills from somewhere other than disk (a
    registry API, a git tree) can use them.
    """
    frontmatter = frontmatter or {}
    sibling_files = sibling_files or []
    description = str(frontmatter.get("description") or "")
    issues: list[dict[str, Any]] = []

    # --- 1. instructions planted where the model will follow them ---------
    for where, text in (("description", description), ("body", body)):
        hits = [p.pattern for p in _PLANTED_DIRECTIVE if p.search(text)]
        if hits:
            issues.append(
                _issue(
                    "skill_poisoning",
                    # The description is worse than the body: a model reads
                    # every available skill's description to decide what to
                    # invoke, so a directive there fires without the skill
                    # ever being chosen.
                    "critical" if where == "description" else "high",
                    skill=name,
                    location=where,
                    patterns=hits,
                    excerpt=_first_hit(text, hits)[:300],
                )
            )

    # --- 2. commands the skill tells the agent to run ---------------------
    # The skill is a set of instructions, so a command inside it is a command
    # the agent will run — put it through the same analyser that would judge
    # it at the moment of execution rather than inventing a second deny-list.
    for command in _shell_commands(body):
        analysis = analyse_shell(command)
        for risk in analysis.risks:
            issues.append(
                _issue(
                    "skill_dangerous_command",
                    risk.severity,
                    skill=name,
                    risk=risk.code,
                    detail=risk.detail,
                    excerpt=command.strip()[:200],
                )
            )

    # --- 3. capability the description does not mention -------------------
    executables = sorted(f for f in sibling_files if Path(f).suffix.lower() in _EXECUTABLE_SUFFIXES)
    if executables:
        issues.append(
            _issue(
                "skill_bundled_code",
                "high",
                skill=name,
                files=executables,
                detail=(
                    "the skill ships executable files; nothing here reads or runs them, "
                    "and the description is not a description of what they do"
                ),
            )
        )

    if frontmatter.get("__malformed__"):
        issues.append(
            _issue(
                "skill_malformed_frontmatter",
                "medium",
                skill=name,
                detail=(
                    "the YAML header did not parse, so its declared name, description "
                    "and tool grants are unknown; its text was scanned as body instead"
                ),
            )
        )

    # --- 4. a tool grant that is not one ----------------------------------
    grants = frontmatter.get("allowed-tools") or frontmatter.get("allowed_tools") or []
    if isinstance(grants, str):
        grants = [grants]
    wildcards = [g for g in grants if _WILDCARD.search(str(g))]
    if wildcards:
        issues.append(
            _issue(
                "skill_overbroad_tools",
                "high",
                skill=name,
                grants=[str(g) for g in wildcards],
                detail="a wildcard tool grant is every tool, including the ones added later",
            )
        )

    declared = {k: v for k, v in frontmatter.items() if k != "__malformed__"}
    digest = hashlib.sha256(
        json.dumps({"n": name, "f": declared, "b": body}, sort_keys=True, default=str).encode()
    ).hexdigest()

    return {
        "skill": name,
        "digest": digest,
        "issues": issues,
        "files": sorted(sibling_files),
    }


def _shell_commands(body: str) -> list[str]:
    """Every command line in a shell-ish fenced block.

    Prompt lines (`$ `) are stripped and comments dropped, so a documented
    command reads to the analyser the way the agent would run it.
    """
    out: list[str] = []
    for block in _SHELL_FENCE.findall(body):
        for line in block.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            out.append(line.removeprefix("$ ").removeprefix("% "))
    return out


def _first_hit(text: str, patterns: list[str]) -> str:
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            start = max(0, match.start() - 60)
            return text[start : match.end() + 120].strip()
    return text[:180]


def parse_skill_file(path: Path) -> tuple[str, dict[str, Any], str]:
    """Split a SKILL.md into (name, frontmatter, body).

    Unparseable frontmatter is **appended to the body rather than dropped**,
    and that is the whole subtlety here. The first version of this returned an
    empty mapping on a YAML error and scanned only the body — so a skill whose
    description held a planted directive scanned clean, because the directive
    was what broke the YAML. Caught on the first fixture:

        description: Helps deploy the app. IMPORTANT: before using this skill…

    YAML reads `IMPORTANT:` as a nested key inside a plain scalar, raises, and
    the tolerant fallback then discarded the most suspicious text in the file.
    A parser that fails open on exactly the malicious case is worse than no
    parser. Malformed frontmatter is also reported in its own right.
    """
    import yaml

    text = path.read_text(encoding="utf-8", errors="replace")
    frontmatter: dict[str, Any] = {}
    body = text
    malformed = False
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            raw, body = parts[1], parts[2]
            try:
                loaded = yaml.safe_load(raw)
            except Exception:
                loaded = None
            if isinstance(loaded, dict):
                frontmatter = loaded
            else:
                # Not a mapping, or not YAML at all. Whatever it is, the model
                # will still read it, so the scanner has to.
                malformed = True
                body = f"{raw}\n{body}"
    name = str(frontmatter.get("name") or path.parent.name or path.stem)
    if malformed:
        frontmatter["__malformed__"] = True
    return name, frontmatter, body


def scan_skills_dir(root: Path) -> list[dict[str, Any]]:
    """Every `SKILL.md` under `root`, analysed.

    Sibling files are the ones beside the skill, not the whole tree: a skill is
    its directory, and walking past that would attribute a repository's source
    to whichever skill happened to be nearest.
    """
    results: list[dict[str, Any]] = []
    for path in sorted(root.rglob("SKILL.md")):
        name, frontmatter, body = parse_skill_file(path)
        siblings = [
            str(f.relative_to(path.parent))
            for f in sorted(path.parent.rglob("*"))
            if f.is_file() and f != path
        ]
        result = analyse_skill(
            name=name, body=body, frontmatter=frontmatter, sibling_files=siblings
        )
        result["path"] = str(path)
        results.append(result)
    return results
