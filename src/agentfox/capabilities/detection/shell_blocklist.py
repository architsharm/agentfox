# Portions ported from agent-governance-claude-code/config/default-policy.json,
# lib/recursive-delete.mjs and lib/policy.mjs in
# https://github.com/microsoft/agent-governance-toolkit (commit c767f83).
# Copyright (c) Microsoft Corporation. Licensed under the MIT License (full text in
# THIRD_PARTY_NOTICES.md). The recursive-delete parser there credits PRs #4129 and
# #4142 by Ricky-G and #3834 by talosrobotics (MIT).
"""A coding agent's command blocklist: what a shell command or a file path must not do.

`actions.analyse_shell` already catches the catastrophic shapes (`rm -rf /`, a
download piped into `sh`, a credential file touched). This module adds a second,
narrower list for the commands a coding agent runs on a developer machine, each with
its own risk code so the coding-agent pack can decide what to do with it:

* ``shell.recursive-delete`` — `rm` with both a recursive and a force flag, found by a
  bounded shell tokenizer rather than a regex, so `rm --rec --fo src`, `sudo -u root
  rm -rf src` and `echo "$(rm -rf src)"` are caught while `echo "rm -rf src"`,
  `git rm -rf --cached src` and `rm -rf node_modules` (a build-artefact cleanup) are
  not;
* ``shell.download-to-shell`` — `curl`/`wget` piped into a shell, or `bash <(curl …)`;
* ``net.cloud-metadata`` — a cloud instance-metadata endpoint, in a command or in any
  URL-valued argument;
* ``shell.secret-read`` — reading a credential file or dumping the environment, except
  a `.env.example`/`.sample`/`.template`;
* ``fs.credential-path`` — a path-valued argument naming a credential file or
  directory, unless the call is a write.

The patterns are the source's, with one change: the shell names after the pipe in the
download rules are word-bounded (`\\b(sh|bash)\\b`), where the source matched them as
substrings, so `curl … | jq .hash` is not a remote-code-execution finding. Python's
`re` stands in for JavaScript's; none of the patterns uses a construct where the two
differ.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# ---------------------------------------------------------------------------
# Command and URL patterns (default-policy.json: blockedToolCalls, urlRules)
# ---------------------------------------------------------------------------

_I = re.IGNORECASE

#: Changed from the source: `(sh|bash)` is word-bounded here (see module docstring).
DOWNLOAD_TO_SHELL = (
    re.compile(r"\bcurl\b[^\n\r|>]*\|[^\n\r]*\b(sh|bash)\b", _I),
    re.compile(r"\bwget\b[^\n\r|>]*\|[^\n\r]*\b(sh|bash)\b", _I),
    re.compile(r"\bbash\b\s+<\([^\n\r]*(curl|wget)", _I),
)

CLOUD_METADATA = re.compile(
    r"https?://(169\.254\.169\.254|100\.100\.100\.200|metadata\.google\.internal)", _I
)

SECRET_READ = (
    re.compile(
        r"\b(cat|less|more|head|tail|sed|awk)\b[^\n\r]*(\.env(\.[\w-]+)?|id_rsa|id_ed25519"
        r"|~/.ssh|/\.ssh/|/\.aws/|/\.azure/|/\.config/gcloud|/\.config/gh/hosts\.yml"
        r"|/\.docker/config\.json|/\.kube/config|/\.netrc|/\.git-credentials|/\.npmrc"
        r"|/\.pypirc|secrets?\.json)",
        _I,
    ),
    re.compile(
        r"\b(Get-Content|gc|type)\b[^\n\r]*(\.env(\.[\w-]+)?|id_rsa|id_ed25519|\\\.ssh\\"
        r"|\\\.aws\\|\\\.azure\\|\\\.config\\gcloud|\\\.config\\gh\\hosts\.yml"
        r"|\\\.docker\\config\.json|\\\.kube\\config|\\\.netrc|\\\.git-credentials"
        r"|\\\.npmrc|\\\.pypirc|secrets?\.json)",
        _I,
    ),
    re.compile(r"\bprintenv\b|\benv\s*(?:$|\|)", _I),
    re.compile(r"\b(Get-ChildItem|gci|dir|ls)\b\s+Env:|\bset\b\s*(?:$|\|)", _I),
)

# directResourcePolicies.pathRules[credential-read-paths]
CREDENTIAL_PATHS = (
    re.compile(
        r"(^|/)(?:\.env(?:\.[\w-]+)?|id_rsa|id_ed25519|\.netrc|\.git-credentials|\.npmrc"
        r"|\.pypirc|docker/config\.json|gh/hosts\.yml|kube/config|credentials|secrets?\.json)$",
        _I,
    ),
    re.compile(
        r"(^|/)(?:\.ssh|\.aws|\.azure|\.config/gcloud|\.config/gh|\.docker|\.kube)(?:/|$)", _I
    ),
    re.compile(r"(^|/)proc/\d+/environ$", _I),
)
CREDENTIAL_PATH_ALLOW = re.compile(r"(^|/)\.env(?:\.[\w-]+)*\.(?:example|sample|template)$", _I)

_SAFE_ENV_TEMPLATE_NAME = re.compile(r"^\.env(?:\.[a-z0-9_-]+)*\.(?:example|sample|template)$", _I)


# ---------------------------------------------------------------------------
# Recursive delete (recursive-delete.mjs)
# ---------------------------------------------------------------------------

#: A substitution contributes an unknown fragment to its enclosing shell word. NUL
#: cannot occur in a shell argument; it keeps dynamic names and options opaque.
_DYNAMIC = "\0"

SAFE_CLEANUP_TARGETS = frozenset(
    {
        "node_modules",
        "dist",
        "build",
        ".next",
        "target",
        "__pycache__",
        ".pytest_cache",
        ".venv",
        "venv",
        "coverage",
        ".turbo",
        "out",
    }
)

_ASSIGNMENT = re.compile(r"^[a-z_][a-z0-9_]*=", _I)


def _last_segment(value: str) -> str:
    parts = [p for p in str(value).split("/") if p]
    return parts[-1] if parts else ""


@dataclass
class _Parsed:
    commands: list[list[str]]
    has_control_operator: bool
    has_redirection: bool
    has_unterminated_syntax: bool


def _tokenize(command_text: str) -> _Parsed:
    """A bounded shell tokenizer, not a shell evaluator (`tokenizeShellCommands`)."""
    text = str(command_text)
    n = len(text)

    def at(i: int) -> str | None:
        return text[i] if 0 <= i < n else None

    commands: list[list[str]] = []
    st: dict[str, Any] = {
        "command": [],
        "token": "",
        "started": False,
        "quoted": False,
        "quote": None,
        "redirect_pending": False,
    }
    substitutions: list[dict[str, Any]] = []
    flags = {"control": False, "redirection": False}
    backtick_depth = 0

    def finish_token() -> None:
        if st["started"]:
            if st["redirect_pending"]:
                st["redirect_pending"] = False
            else:
                st["command"].append(st["token"])
            st["token"] = ""
            st["started"] = False
            st["quoted"] = False

    def finish_command() -> None:
        finish_token()
        if st["command"]:
            commands.append(st["command"])
            st["command"] = []

    def start_substitution(frame: dict[str, Any]) -> None:
        frame["enclosing"] = dict(st)
        substitutions.append(frame)
        st.update(command=[], token="", started=False, quoted=False, quote=None)
        st["redirect_pending"] = False

    def finish_substitution() -> None:
        nonlocal backtick_depth
        finish_command()
        frame = substitutions.pop()
        st.update(frame["enclosing"])
        st["token"] += _DYNAMIC
        st["started"] = True
        st["quoted"] = True
        if frame["type"] == "backtick":
            backtick_depth -= 1

    index = 0
    while index < n:
        character = text[index]
        if st["quote"]:
            if st["quote"] == '"' and character == "`":
                flags["control"] = True
                start_substitution({"type": "backtick"})
                backtick_depth += 1
                index += 1
                continue
            if st["quote"] == '"' and character == "$" and at(index + 1) == "(":
                flags["control"] = True
                start_substitution({"depth": 1, "type": "command"})
                index += 2
                continue
            if character == st["quote"]:
                st["quote"] = None
            elif st["quote"] == '"' and character == "\\" and index + 1 < n:
                following = text[index + 1]
                if following in ('"', "\\", "$", "`"):
                    st["token"] += following
                    index += 1
                elif following not in ("\n", "\r"):
                    st["token"] += character
            else:
                st["token"] += character
            st["started"] = True
            index += 1
            continue

        active = substitutions[-1] if substitutions else None
        if character == "`" and active is not None and active["type"] == "backtick":
            flags["control"] = True
            finish_substitution()
            index += 1
            continue
        if character == "`":
            flags["control"] = True
            start_substitution({"type": "backtick"})
            backtick_depth += 1
            index += 1
            continue
        if character in ("<", ">") and at(index + 1) == "(":
            flags["control"] = True
            start_substitution({"depth": 1, "type": "command"})
            index += 2
            continue
        if character == "$" and at(index + 1) == "(":
            flags["control"] = True
            start_substitution({"depth": 1, "type": "command"})
            index += 2
            continue
        if active is not None and active["type"] == "command" and character == "(":
            flags["control"] = True
            finish_command()
            active["depth"] += 1
            index += 1
            continue
        if active is not None and active["type"] == "command" and character == ")":
            flags["control"] = True
            active["depth"] -= 1
            if active["depth"] == 0:
                finish_substitution()
            else:
                finish_command()
            index += 1
            continue

        follows_expansion = at(index - 1) in ("{", "}", ")", "`")
        if character == "#" and not st["started"] and not follows_expansion:
            inside_backtick = backtick_depth > 0
            backslashes = 0
            while index + 1 < n:
                following = text[index + 1]
                if (
                    following in ("\n", "\r")
                    or inside_backtick
                    and following == "`"
                    and backslashes % 2 == 0
                ):
                    break
                backslashes = backslashes + 1 if following == "\\" else 0
                index += 1
            finish_command()
            if at(index + 1) == "\r" and at(index + 2) == "\n":
                flags["control"] = True
                index += 2
            elif at(index + 1) in ("\n", "\r"):
                flags["control"] = True
                index += 1
            index += 1
            continue

        if character in ("'", '"'):
            st["quote"] = character
            st["started"] = True
            st["quoted"] = True
            index += 1
            continue
        if character == "\\":
            following = at(index + 1)
            if following == "\n":
                index += 2
                continue
            if following == "\r" and at(index + 2) == "\n":
                index += 3
                continue
            if following is not None:
                st["token"] += following
                st["started"] = True
                st["quoted"] = True
                index += 2
            else:
                st["token"] += character
                st["started"] = True
                index += 1
            continue
        if character in (" ", "\t", "\r", "\n"):
            finish_token()
            if character in ("\n", "\r"):
                flags["control"] = True
                finish_command()
                if character == "\r" and at(index + 1) == "\n":
                    index += 1
            index += 1
            continue
        if character in (">", "<") or (character == "&" and at(index + 1) == ">"):
            # Redirection syntax and its operand are not rm arguments. Quoted or
            # escaped operators never enter this branch and remain literal words.
            flags["redirection"] = True
            if not st["quoted"] and re.fullmatch(r"\d+", st["token"]):
                st["token"] = ""
                st["started"] = False
            else:
                finish_token()
            operator = character
            if character == "&":
                index += 1
                operator += text[index]
            if at(index + 1) == ">" and operator.endswith(">"):
                index += 1
            elif at(index + 1) == "<" and character == "<":
                index += 1
                if at(index + 1) == "<" or at(index + 1) == "-":
                    index += 1
            elif at(index + 1) in ("&", "|") or (character == "<" and at(index + 1) == ">"):
                index += 1
            st["redirect_pending"] = True
            index += 1
            continue
        if character in ";|&(){} `":
            flags["control"] = True
            finish_command()
            if character in ("|", "&") and at(index + 1) == character:
                index += 1
            index += 1
            continue

        st["token"] += character
        st["started"] = True
        index += 1

    unterminated = bool(st["quote"] or substitutions or st["redirect_pending"])
    # Keep static outer flags visible even if an inner substitution never closes.
    # The malformed-syntax flag still prohibits the cleanup exception.
    while substitutions:
        finish_substitution()
    finish_command()
    return _Parsed(commands, flags["control"], flags["redirection"], unterminated)


def _sudo_option(option: str) -> tuple[bool, bool]:
    """(non_executing, takes_argument) for a sudo/doas option."""
    if option.startswith("--"):
        name = option.split("=")[0]
        return (
            name in ("--list", "--version", "--help"),
            "=" not in option
            and name
            in (
                "--user",
                "--group",
                "--host",
                "--prompt",
                "--close-from",
                "--chdir",
                "--chroot",
                "--command-timeout",
                "--role",
                "--type",
            ),
        )
    for position, letter in enumerate(option[1:]):
        if letter in "lV":
            return True, False
        if letter in "ughpCDRTrt":
            # Any remaining characters belong to the argument, not to more flags.
            return False, position == len(option) - 2
    return False, False


_WRAPPER_ARGS = {
    "nice": {"-n", "--adjustment"},
    "time": {"-f", "--format", "-o", "--output"},
    "timeout": {"-k", "--kill-after", "-s", "--signal"},
}


def _invocation(tokens: list[str]) -> tuple[str, list[str]] | None:
    """The command a token list runs, past assignments and wrappers."""

    def tok(i: int) -> str | None:
        return tokens[i] if 0 <= i < len(tokens) else None

    index = 0
    while index < len(tokens):
        token = tokens[index]
        # Assignment values may be dynamic; an executable name may not be inferred.
        if _DYNAMIC in token and not _ASSIGNMENT.match(token):
            return None
        name = _last_segment(token.replace("\\", "/")).lower()
        if name in ("if", "then", "do", "else", "elif", "while", "until", "in") or (
            _ASSIGNMENT.match(token)
        ):
            index += 1
            continue
        if name == "exec":
            index += 1
            while (tok(index) or "").startswith("-"):
                index += 2 if tokens[index] == "-a" else 1
            continue
        if name in ("command", "nohup", "busybox"):
            index += 1
            while (tok(index) or "").startswith("-"):
                option = tokens[index]
                index += 1
                if option == "--":
                    break
                # Lookup/help modes do not execute the following command.
                if (name == "command" and re.match(r"^-[^-]*[vV]", option)) or option in (
                    "--help",
                    "--version",
                    "--list",
                    "--list-full",
                ):
                    return None
            continue
        if name in _WRAPPER_ARGS:
            index += 1
            while (tok(index) or "").startswith("-"):
                option = tokens[index]
                index += 1
                if option == "--":
                    break
                if option in _WRAPPER_ARGS[name]:
                    index += 1
            if name == "timeout" and index < len(tokens):
                index += 1
            continue
        if name == "env":
            index += 1
            while index < len(tokens):
                argument = tokens[index]
                if argument in ("--help", "--version"):
                    return None
                if argument == "--":
                    index += 1
                    break
                if argument in ("-u", "--unset", "-C", "--chdir"):
                    index += 2
                elif argument.startswith("-") or _ASSIGNMENT.match(argument):
                    index += 1
                else:
                    break
            continue
        if name in ("sudo", "doas"):
            index += 1
            while index < len(tokens) and tokens[index].startswith("-"):
                option = tokens[index]
                index += 1
                if option == "--":
                    break
                non_executing, takes_argument = _sudo_option(option)
                if name == "sudo" and non_executing:
                    return None
                if takes_argument:
                    index += 1
            continue
        return name, tokens[index + 1 :]
    return None


@dataclass(frozen=True)
class _RmOption:
    recursive: bool
    force: bool
    recognized: bool


def _rm_option(token: str) -> _RmOption | None:
    if _DYNAMIC in token or token == "-" or not token.startswith("-"):
        return None
    if token.startswith("--"):
        name = token[2:].split("=")[0].lower()
        if name.startswith("r") and "recursive".startswith(name):
            return _RmOption(recursive=True, force=False, recognized=True)
        if name.startswith("f") and "force".startswith(name):
            return _RmOption(recursive=False, force=True, recognized=True)
        known = (
            "dir",
            "help",
            "interactive",
            "no-preserve-root",
            "one-file-system",
            "preserve-root",
            "verbose",
            "version",
        )
        return _RmOption(recursive=False, force=False, recognized=name in known)
    letters = token[1:].lower()
    return _RmOption(
        recursive="r" in letters,
        force="f" in letters,
        recognized=all(letter in "firdv" for letter in letters),
    )


def matches_recursive_delete(command_text: str) -> bool:
    """True when any command in the text is `rm` with recursive and force flags."""
    for tokens in _tokenize(command_text).commands:
        invocation = _invocation(tokens)
        if invocation is None or invocation[0] != "rm":
            continue
        recursive = force = False
        for token in invocation[1]:
            if token == "--":
                break
            option = _rm_option(token)
            if option:
                recursive = recursive or option.recursive
                force = force or option.force
        if recursive and force:
            return True
    return False


def _add_cleanup_target(targets: list[str], token: str) -> bool:
    # Never discard an uncertain target: doing so can exempt a mixed-target delete.
    # Commas are literal filename characters in a POSIX shell, not list separators.
    cleaned = re.sub(r"/+$", "", token)
    if not cleaned or _DYNAMIC in cleaned or re.search(r"[\\*?\[\]{}$<>`]", cleaned):
        return False
    targets.append(cleaned)
    return True


def _safe_cleanup_target(target: str) -> bool:
    if (
        not target
        or target.startswith("/")
        or re.match(r"^[a-z]:", target, _I)
        or ".." in target
        or "~" in target
    ):
        return False
    return _last_segment(re.sub(r"^\./", "", target)) in SAFE_CLEANUP_TARGETS


def is_safe_cleanup(command_text: str) -> bool:
    """A single plain `rm -rf` of build artefacts only (`node_modules`, `dist`, …)."""
    parsed = _tokenize(command_text)
    if (
        parsed.has_control_operator
        or parsed.has_unterminated_syntax
        or parsed.has_redirection
        or len(parsed.commands) != 1
    ):
        return False
    invocation = _invocation(parsed.commands[0])
    if invocation is None or invocation[0] != "rm":
        return False
    targets: list[str] = []
    options_ended = False
    for token in invocation[1]:
        if not token:
            return False
        if options_ended:
            if not _add_cleanup_target(targets, token):
                return False
            continue
        if token == "--":
            options_ended = True
            continue
        if token.startswith("-"):
            option = _rm_option(token)
            if option is None or not option.recognized:
                return False
            continue
        if not _add_cleanup_target(targets, token):
            return False
    return bool(targets) and all(_safe_cleanup_target(t) for t in targets)


# ---------------------------------------------------------------------------
# Secret reads: the .env template exemption (policy.mjs isSafeEnvTemplateReadCommand)
# ---------------------------------------------------------------------------


def _is_env_template_read(command_text: str) -> bool:
    if re.search(r"(?:&&|\|\||[;`]|[\r\n])", command_text):
        return False
    tokens = re.findall(r"\"[^\"]*\"|'[^']*'|\S+", command_text)
    stripped = [re.sub(r"^['\"]|['\"]$", "", t) for t in tokens]
    sensitive = [t for t in stripped if t and ".env" in t]
    return bool(sensitive) and all(
        _SAFE_ENV_TEMPLATE_NAME.match(_last_segment(t.replace("\\", "/"))) for t in sensitive
    )


# ---------------------------------------------------------------------------
# What the action analyser calls
# ---------------------------------------------------------------------------


def command_risks(command: str) -> list[tuple[str, str]]:
    """``(code, detail)`` for every blocklist entry a shell command matches."""
    out: list[tuple[str, str]] = []
    if matches_recursive_delete(command) and not is_safe_cleanup(command):
        out.append(("shell.recursive-delete", "recursive forced delete outside build artefacts"))
    if any(p.search(command) for p in DOWNLOAD_TO_SHELL):
        out.append(("shell.download-to-shell", "runs a downloaded script in a shell"))
    if CLOUD_METADATA.search(command):
        out.append(("net.cloud-metadata", "reaches a cloud instance-metadata endpoint"))
    if any(p.search(command) for p in SECRET_READ) and not _is_env_template_read(command):
        out.append(("shell.secret-read", "reads a credential file or dumps the environment"))
    return out


_PATH_KEY = re.compile(
    r"(path|file|filename|target|targets|destination|dest|output|cwd|workspace|root|dir"
    r"|directory)",
    _I,
)
_WRITE_TOOL = re.compile(r"(edit|create|write|save|append|move|rename|copy)", _I)
_WRITE_KEY = re.compile(r"(output|destination|dest|save|write|create|new)", _I)


def url_risk(value: str) -> tuple[str, str] | None:
    """A URL-valued argument (any key) that targets a metadata endpoint."""
    text = str(value).strip()
    if re.match(r"^https?://", text, _I) and CLOUD_METADATA.search(text):
        return ("net.cloud-metadata", "reaches a cloud instance-metadata endpoint")
    return None


def path_risk(key: str, value: str, tool: str | None = None) -> tuple[str, str] | None:
    """A path-valued argument naming a credential file or directory, on a read.

    A call counts as a write, and is not checked, when the tool's name or the
    argument's name says so (`Write`, `Edit`, `output_path`), as in the source.
    """
    text = str(value).strip()
    if not text or re.match(r"^https?://", text, _I) or not _PATH_KEY.search(str(key)):
        return None
    if _WRITE_TOOL.search(str(tool or "")) or _WRITE_KEY.search(str(key)):
        return None
    normalized = text.replace("\\", "/").rstrip("/").lower()
    if not any(p.search(normalized) for p in CREDENTIAL_PATHS):
        return None
    if CREDENTIAL_PATH_ALLOW.search(normalized):
        return None
    return ("fs.credential-path", "names a credential file or directory")


__all__ = [
    "command_risks",
    "is_safe_cleanup",
    "matches_recursive_delete",
    "path_risk",
    "url_risk",
]
