"""What the AI tools on this machine are set up to do, outside any one repository.

A repository scan sees the MCP servers a project commits. Most are not committed: they
are added once, at user level, to Claude Code, Cursor, Claude Desktop, Codex or VS Code,
and then load in every session. Skills are the same: a skill installed under
``~/.claude/skills`` is read by every Claude Code session on the machine. This module
reads those user-level files.

Static and offline, like the rest of discovery: configs and ``SKILL.md`` files are
read, nothing is started, nothing is written, and nothing leaves the machine. Env
values in a config are never copied into the report; only their names are.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agentfox.capabilities.discovery.exposure import (
    FLAG_LABEL,
    Member,
    classify_mcp_server,
    mcp_loadouts,
    server_hygiene,
    trifecta_sentence,
)
from agentfox.capabilities.discovery.skills import scan_skills_dir


@dataclass(frozen=True)
class UserConfig:
    """One user-level MCP client config: where it lives and which client reads it."""

    path: Path
    client: str
    label: str


def _app_dirs(home: Path, env: Mapping[str, str], platform: str) -> list[Path]:
    """Where desktop apps keep their per-user settings on this OS."""
    if platform == "darwin":
        return [home / "Library" / "Application Support"]
    if platform.startswith("win"):
        appdata = env.get("APPDATA")
        return [Path(appdata)] if appdata else [home / "AppData" / "Roaming"]
    xdg = env.get("XDG_CONFIG_HOME")
    return [Path(xdg)] if xdg else [home / ".config"]


def user_mcp_configs(
    home: Path | None = None,
    *,
    env: Mapping[str, str] | None = None,
    platform: str | None = None,
) -> list[UserConfig]:
    """Every user-level MCP client config that exists on this machine."""
    home = home or Path.home()
    env = os.environ if env is None else env
    platform = platform or sys.platform
    candidates: list[tuple[Path, str]] = [
        (home / ".claude.json", "Claude Code"),
        (home / ".claude" / "settings.json", "Claude Code"),
        (home / ".cursor" / "mcp.json", "Cursor"),
        (home / ".codeium" / "windsurf" / "mcp_config.json", "Windsurf"),
        (home / ".gemini" / "settings.json", "Gemini CLI"),
        (home / ".codex" / "config.toml", "Codex"),
    ]
    for base in _app_dirs(home, env, platform):
        candidates += [
            (base / "Claude" / "claude_desktop_config.json", "Claude Desktop"),
            (base / "Code" / "User" / "mcp.json", "VS Code"),
            (base / "Code" / "User" / "settings.json", "VS Code"),
            (
                base
                / "Code"
                / "User"
                / "globalStorage"
                / "saoudrizwan.claude-dev"
                / "settings"
                / "cline_mcp_settings.json",
                "Cline",
            ),
        ]
    found: list[UserConfig] = []
    for path, client in candidates:
        if path.is_file():
            found.append(UserConfig(path, client, _tilde(path, home)))
    return found


def user_skill_dirs(home: Path | None = None) -> list[Path]:
    """The user-level directories agents load skills from, where they exist."""
    home = home or Path.home()
    dirs = [
        home / ".claude" / "skills",
        home / ".claude" / "plugins",
        home / ".codex" / "skills",
        home / ".agents" / "skills",
    ]
    return [d for d in dirs if d.is_dir()]


def _tilde(path: Path, home: Path) -> str:
    try:
        return "~/" + path.relative_to(home).as_posix()
    except ValueError:
        return str(path)


@dataclass
class MachineReport:
    """The user-level MCP servers and skills on one machine, and what is wrong with them."""

    configs: list[dict[str, str]] = field(default_factory=list)
    servers: list[dict[str, Any]] = field(default_factory=list)
    trifectas: list[str] = field(default_factory=list)
    skill_dirs: list[str] = field(default_factory=list)
    skills: list[dict[str, Any]] = field(default_factory=list)

    @property
    def skill_issues(self) -> int:
        return sum(len(s["issues"]) for s in self.skills)

    @property
    def critical(self) -> bool:
        """A lethal trifecta, or a critical issue in a config or a skill."""
        return bool(self.trifectas) or any(
            issue.get("severity") == "critical"
            for item in [*self.servers, *self.skills]
            for issue in item.get("issues", [])
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "configs": self.configs,
            "servers": self.servers,
            "lethal_trifectas": self.trifectas,
            "skill_dirs": self.skill_dirs,
            "skills": self.skills,
            "critical": self.critical,
        }


def scan_machine(
    home: Path | None = None,
    *,
    env: Mapping[str, str] | None = None,
    platform: str | None = None,
    skills: bool = True,
) -> MachineReport:
    """Read every user-level MCP config and skill directory on this machine."""
    home = home or Path.home()
    report = MachineReport()
    seen: set[tuple[str, str]] = set()
    for config in user_mcp_configs(home, env=env, platform=platform):
        loadouts = mcp_loadouts(config.path, label=config.label)
        if not loadouts:
            continue
        report.configs.append({"client": config.client, "path": config.label})
        for label, decls in loadouts:
            for decl in decls:
                if (config.label, decl.name) in seen:
                    continue
                seen.add((config.label, decl.name))
                caps = classify_mcp_server(decl)
                report.servers.append(
                    {
                        "server": decl.name,
                        "client": config.client,
                        "config": config.label,
                        "launch": decl.launch,
                        "pinned_version": decl.pinned_version,
                        "known": caps.known,
                        "reaches": [caps.phrases.get(f, FLAG_LABEL[f]) for f in caps.ordered()],
                        "issues": server_hygiene(decl),
                        "env_keys": sorted(decl.env),
                    }
                )
            members = [Member(d.name, classify_mcp_server(d), d.config, 1) for d in decls]
            unknown = [m.name for m in members if not m.caps.known]
            found = trifecta_sentence(f"{config.client}, {label}", members, unknown=unknown)
            if found and found[0] not in report.trifectas:
                report.trifectas.append(found[0])
    if skills:
        for directory in user_skill_dirs(home):
            report.skill_dirs.append(_tilde(directory, home))
            for result in scan_skills_dir(directory):
                result["path"] = _tilde(Path(result["path"]), home)
                report.skills.append(result)
    return report
