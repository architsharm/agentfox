"""What an agent can reach — and whether it adds up to the lethal trifecta.

A list of tool names is not a finding a security owner can act on. "send_email" is
fine. "fetch_url" is fine. "read_customer_record" is fine. All three in the same agent
is the lethal trifecta (Simon Willison's term): the agent can read private data, it
reads content an attacker can write, and it has a way to send data out. An
instruction hidden in a web page can then make it mail the customer table to anyone.
That sentence is the finding; the tool list is the evidence.

So every tool and every MCP server a static scan finds is classified into three flags:

* ``private_data`` — it can read something that is not public (records, files,
  inboxes, databases).
* ``untrusted_input`` — it brings in content someone outside can author (web pages,
  search results, incoming email, issue comments).
* ``exfiltration`` — it can send data out or act irreversibly (send, post, pay,
  refund, delete, write, run a shell command, make an outbound request).

The classification is a name-and-description heuristic, deliberately: this runs on a
repository nobody has imported, and a tool's name is usually the most honest
description of it there is. It reuses :func:`agentfox.integrations.mcp.infer_impact`
and the AgentDojo irreversible-tool pattern the benchmarks grade against, so the scan
and the runtime agree on what "irreversible" means. A tool whose name says nothing is
left unflagged rather than guessed at, and an MCP server this module does not know is
reported as unknown — never as safe.

Static and offline, like the rest of discovery: MCP server *configs* are read, the
servers are never started.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PRIVATE = "private_data"
UNTRUSTED = "untrusted_input"
EXFIL = "exfiltration"
FLAGS = (PRIVATE, UNTRUSTED, EXFIL)

#: How each flag reads to someone who has never heard of the trifecta.
FLAG_LABEL = {
    PRIVATE: "reads private data",
    UNTRUSTED: "reads untrusted content",
    EXFIL: "can send data out or act irreversibly",
}

#: The pattern `benchmarks/agentdojo_e2e/run_agentdojo_e2e.py` grades irreversible
#: tools with. Kept identical so a tool the benchmark calls irreversible is one the
#: scan calls an exfiltration channel.
_AGENTDOJO_IRREVERSIBLE = re.compile(
    r"^(send_money|schedule_transaction|update_scheduled_transaction|update_password|"
    r"send_email|send_direct_message|post_webpage|delete_\w+|remove_\w+|reserve_\w+)$"
)

# -- name vocabulary ---------------------------------------------------------
#
# Matched against whole tokens of the tool name (`read_customer_record` ->
# read, customer, record), never substrings: "drop" in "dropdown" and "send" in
# "sender" are how a substring heuristic produces a wall of nonsense.

_READ_VERBS = {
    "read", "get", "list", "search", "lookup", "find", "query", "load", "retrieve",
    "view", "show", "fetch", "export", "open", "cat", "describe", "check",
}  # fmt: skip

_PRIVATE_NOUNS = {
    "customer", "customers", "client", "clients", "user", "users", "account",
    "accounts", "profile", "profiles", "record", "records", "patient", "patients",
    "employee", "employees", "contact", "contacts", "inbox", "email", "emails",
    "mail", "message", "messages", "file", "files", "document", "documents", "doc",
    "docs", "database", "db", "sql", "table", "crm", "invoice", "invoices", "order",
    "orders", "transaction", "transactions", "balance", "payment", "payments",
    "ssn", "secret", "secrets", "credential", "credentials", "password", "salary",
    "ticket", "tickets", "calendar", "event", "events", "note", "notes", "drive",
    "repo", "repository", "history", "memory", "address", "phone", "iban",
    "medical", "health", "card",
}  # fmt: skip

#: Nouns that are about the outside world, so a read verb on them is untrusted input,
#: not private data.
_WEB_NOUNS = {
    "url", "urls", "web", "webpage", "website", "page", "html", "http", "https",
    "internet", "browser", "browse", "scrape", "crawl", "rss", "feed", "google",
    "bing", "serp", "download", "link",
}  # fmt: skip

#: Content an outside party authors even though it arrives through a private system.
_INBOUND_NOUNS = {
    "inbox", "email", "emails", "mail", "message", "messages", "comment", "comments",
    "issue", "issues", "review", "reviews", "ticket", "tickets",
}  # fmt: skip

_EXFIL_VERBS = {
    "send", "post", "publish", "upload", "share", "forward", "reply", "tweet",
    "notify", "webhook", "pay", "refund", "transfer", "wire", "charge", "payout",
    "delete", "drop", "remove", "purge", "truncate", "destroy", "revoke", "write",
    "exec", "execute", "shell", "bash", "deploy", "invite", "sms", "email", "mail",
    "dm", "submit", "push", "withdraw",
}  # fmt: skip

#: Verbs that change a thing without reading anything back from it.
_WRITE_VERBS = {
    "create", "update", "add", "set", "insert", "edit", "modify", "cancel", "schedule",
    "append", "save", "put", "patch",
}  # fmt: skip

_TOKEN_SPLIT = re.compile(r"[^a-z0-9]+")
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def tokens(name: str) -> list[str]:
    """`readCustomerRecord` / `read-customer.record` -> [read, customer, record]."""
    return [t for t in _TOKEN_SPLIT.split(_CAMEL.sub("_", name).lower()) if t]


def _plural(noun: str) -> str:
    return noun if noun.endswith("s") else noun + "s"


@dataclass
class Capabilities:
    """The three flags, with the plain-English phrase behind each one that is set."""

    flags: set[str] = field(default_factory=set)
    #: flag -> how this tool does it, e.g. "can read customer records".
    phrases: dict[str, str] = field(default_factory=dict)
    #: The noun the private data is about ("customer"), for the risk sentence.
    data_noun: str | None = None
    #: What kind of untrusted content ("a web page", "an email").
    source: str | None = None
    #: What the exfiltration channel does in a sentence ("send customer data out").
    action: str | None = None
    #: False for an MCP server this module has no knowledge of.
    known: bool = True

    def ordered(self) -> list[str]:
        return [f for f in FLAGS if f in self.flags]


def classify_tool(name: str, description: str = "") -> Capabilities:
    """Classify one tool by its name, falling back to its description."""
    from .integrations.mcp import infer_impact

    toks = tokens(name)
    tset = set(toks)
    desc = (description or "").lower()
    caps = Capabilities()

    # -- can it send something out, or do something it cannot undo? ----------
    reads = bool(tset & _READ_VERBS)
    # "email" is a verb in `email_customer` and a noun in `read_email`.
    exfil_hits = [t for t in toks if t in _EXFIL_VERBS and not (reads and t in ("email", "mail"))]
    if (
        exfil_hits
        or _AGENTDOJO_IRREVERSIBLE.match(name)
        # Name only, and only for a name that is not a read: a description saying
        # "the sender's address" is not a send, and neither is `get_sender`.
        or (not reads and infer_impact(name) == "irreversible")
    ):
        caps.flags.add(EXFIL)
        caps.phrases[EXFIL], caps.action = _exfil_phrase(tset)

    # -- does it bring in content an outsider can write? ---------------------
    # `create_ticket` and `post_webpage` write to those things; they read nothing in.
    reading = reads or not (exfil_hits or tset & _WRITE_VERBS)
    web = reading and bool(tset & _WEB_NOUNS or ("fetch" in tset and not (tset & _PRIVATE_NOUNS)))
    inbound = tset & _INBOUND_NOUNS if reading else set()
    if (
        reading
        and not web
        and not inbound
        and re.search(r"\b(web ?page|website|url|internet)\b", desc)
    ):
        web = True
    if web:
        caps.flags.add(UNTRUSTED)
        caps.phrases[UNTRUSTED] = "reads untrusted web pages"
        caps.source = "a web page"
    elif inbound:
        caps.flags.add(UNTRUSTED)
        noun = sorted(inbound)[0]
        if noun in ("inbox", "email", "emails", "mail"):
            caps.phrases[UNTRUSTED] = "reads incoming email"
            caps.source = "an email"
        else:
            caps.phrases[UNTRUSTED] = f"reads {_plural(noun)} other people write"
            caps.source = f"a {noun.rstrip('s')}"

    # -- does it read something private? -------------------------------------
    nouns = [t for t in toks if t in _PRIVATE_NOUNS]
    if nouns and reading and not web:
        caps.flags.add(PRIVATE)
        # "read_customer_record" -> "customer records": every non-verb token, in order.
        subject = " ".join(t for t in toks if t not in _READ_VERBS)
        subject = subject or nouns[0]
        words = subject.split()
        words[-1] = _plural(words[-1])
        caps.phrases[PRIVATE] = f"can read {' '.join(words)}"
        noun = nouns[0]
        caps.data_noun = noun if noun in ("ssn", "credentials", "address") else noun.rstrip("s")
    elif (
        not nouns
        and reading
        and not web
        and re.search(
            r"\b(customer|patient|personal|private|confidential|pii|account holder)\b", desc
        )
    ):
        caps.flags.add(PRIVATE)
        caps.phrases[PRIVATE] = "reads private data"
    return caps


def _exfil_phrase(tset: set[str]) -> tuple[str, str]:
    """(what it can do, what an attacker could make it do) for an exfiltration tool."""
    if tset & {"pay", "refund", "transfer", "wire", "charge", "payout", "money", "withdraw"}:
        return "can move money", "move money"
    if tset & {"email", "mail"}:
        return "can send email", "send {data} out"
    if tset & {"sms", "dm", "message", "messages", "notify", "slack", "tweet"}:
        return "can send messages", "send {data} out"
    if tset & {"delete", "drop", "remove", "purge", "truncate", "destroy"}:
        return "can delete data", "delete data"
    if tset & {"exec", "execute", "shell", "bash", "command"}:
        return "can run shell commands", "run commands on this machine"
    if tset & {"post", "webhook", "http", "request", "upload", "publish", "share", "push"}:
        return "can send data to other systems", "send {data} out"
    if tset & {"write"}:
        return "can write files", "write {data} somewhere it can be read"
    return "can act irreversibly", "act on {data}"


# ---------------------------------------------------------------------------
# MCP servers, from config
# ---------------------------------------------------------------------------

#: Config files an MCP client reads. Every one is a file the scanner can open without
#: starting anything.
MCP_CONFIG_NAMES = (
    ".mcp.json",
    "mcp.json",
    "claude_desktop_config.json",
    "mcp_settings.json",
    ".claude.json",
)

#: Where `agentfox scan mcp` looks when no `--config` is given, relative to the repo.
MCP_CONFIG_CANDIDATES = (
    ".mcp.json",
    "mcp.json",
    ".cursor/mcp.json",
    ".claude/settings.json",
    ".claude/settings.local.json",
    ".claude.json",
    "claude_desktop_config.json",
    "mcp_settings.json",
)

#: Known servers, matched against the server's name and how it is launched (package
#: name, image, URL). The order matters: the first match wins, so the specific names
#: come before the generic ones. Flags are what the server is *for*; an operator can
#: always narrow it with the real tool list (`agentfox scan mcp NAME --file`).
_KnownServer = tuple[tuple[str, ...], set[str], dict[str, str], str | None, str | None]
_KNOWN_SERVERS: tuple[_KnownServer, ...] = (
    (
        ("gmail", "outlook", "email", "imap"),
        {PRIVATE, UNTRUSTED, EXFIL},
        {PRIVATE: "reads your mailbox", UNTRUSTED: "reads incoming email", EXFIL: "can send email"},
        "an email",
        "send {data} out",
    ),
    (
        ("slack", "discord", "teams", "telegram", "whatsapp"),
        {PRIVATE, UNTRUSTED, EXFIL},
        {
            PRIVATE: "reads private channels",
            UNTRUSTED: "reads messages other people write",
            EXFIL: "can post messages",
        },
        "a chat message",
        "send {data} out",
    ),
    (
        ("github", "gitlab", "bitbucket", "linear", "jira", "atlassian", "notion", "asana"),
        {PRIVATE, UNTRUSTED, EXFIL},
        {
            PRIVATE: "reads private repositories and tickets",
            UNTRUSTED: "reads issues and comments anyone can write",
            EXFIL: "can create issues, comments and pull requests",
        },
        "an issue comment",
        "publish {data}",
    ),
    (
        (
            "fetch",
            "browser",
            "puppeteer",
            "playwright",
            "web-search",
            "websearch",
            "brave-search",
            "brave",
            "tavily",
            "exa",
            "firecrawl",
            "perplexity",
            "serp",
            "scrape",
            "crawl",
            "duckduckgo",
        ),
        {UNTRUSTED, EXFIL},
        {
            UNTRUSTED: "reads untrusted web pages",
            EXFIL: "can send data out in the URLs it requests",
        },
        "a web page",
        "send {data} out",
    ),
    (
        ("filesystem", "file-system", "files", "fs"),
        {PRIVATE, EXFIL},
        {PRIVATE: "reads files on this machine", EXFIL: "can write and overwrite files"},
        None,
        "write {data} somewhere it can be read",
    ),
    (
        (
            "postgres",
            "postgresql",
            "mysql",
            "sqlite",
            "mongodb",
            "mongo",
            "supabase",
            "database",
            "redis",
            "bigquery",
            "snowflake",
            "db",
        ),
        {PRIVATE, EXFIL},
        {PRIVATE: "reads a database", EXFIL: "can modify or delete rows"},
        None,
        "delete data",
    ),
    (
        ("shell", "terminal", "desktop-commander", "exec", "bash", "computer-use"),
        {PRIVATE, EXFIL},
        {PRIVATE: "reads anything on this machine", EXFIL: "can run shell commands"},
        None,
        "run commands on this machine",
    ),
    (
        ("git",),
        {PRIVATE},
        {PRIVATE: "reads the git repository"},
        None,
        None,
    ),
    (
        ("memory", "knowledge-graph"),
        {PRIVATE},
        {PRIVATE: "reads what earlier sessions stored"},
        None,
        None,
    ),
)

#: Servers known to touch nothing private and send nothing out.
_INERT_SERVERS = ("time", "everything", "sequential-thinking", "sequentialthinking", "calculator")


@dataclass
class McpServerDecl:
    """One MCP server as a client config declares it. Nothing here was executed."""

    name: str
    config: str  # path of the config file, relative to the scan root when possible
    command: str = ""
    args: list[str] = field(default_factory=list)
    url: str = ""
    transport: str = "stdio"
    headers: dict[str, Any] = field(default_factory=dict)
    env: dict[str, Any] = field(default_factory=dict)

    @property
    def launch(self) -> str:
        """How the server starts, in one line, without any env values."""
        if self.url:
            return self.url
        return " ".join([self.command, *self.args]).strip()

    @property
    def package(self) -> str:
        """The package the launcher runs (`npx -y @scope/pkg@1.2` -> `@scope/pkg@1.2`)."""
        launcher = Path(self.command).name
        positional = [a for a in self.args if not a.startswith("-")]
        if launcher in ("npx", "pnpx", "bunx", "uvx", "pipx") and positional:
            return (
                positional[0]
                if launcher != "pipx" or positional[0] != "run"
                else (positional[1] if len(positional) > 1 else "")
            )
        if launcher == "docker" and "run" in positional:
            images = [a for a in positional if a != "run"]
            return images[0] if images else ""
        return ""

    @property
    def pinned_version(self) -> str | None:
        """The version the config pins, or None if it floats."""
        pkg = self.package
        if not pkg:
            return None
        launcher = Path(self.command).name
        if launcher == "docker":
            if "@sha256:" in pkg:
                return pkg.split("@sha256:")[1][:16]
            tag = pkg.rsplit(":", 1)[1] if ":" in pkg.split("/")[-1] else ""
            return tag if tag and tag != "latest" else None
        if launcher in ("uvx", "pipx"):
            match = re.search(r"==([\w.]+)", pkg)
            return match.group(1) if match else None
        # npm: @scope/name@1.2.3 or name@1.2.3 — the leading @ of a scope is not a pin.
        body = pkg[1:] if pkg.startswith("@") else pkg
        if "@" in body:
            version = body.rsplit("@", 1)[1]
            return version if version and version not in ("latest", "next") else None
        return None

    def to_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "config": self.config,
            "transport": self.transport,
            "launch": self.launch,
            "package": self.package or None,
            "pinned_version": self.pinned_version,
            # Names only: an env value is where a config keeps its token.
            "env_keys": sorted(self.env),
        }


def parse_mcp_config(path: Path, *, root: Path | None = None) -> list[McpServerDecl]:
    """Every server one config file declares. Unreadable or non-MCP JSON -> []."""
    try:
        data = json.loads(path.read_text(errors="ignore"))
    except (OSError, ValueError):
        return []
    if not isinstance(data, dict):
        return []
    try:
        label = str(path.resolve().relative_to(root.resolve())) if root else str(path)
    except ValueError:
        label = str(path)

    blocks: list[dict[str, Any]] = []
    for key in ("mcpServers", "servers"):
        if isinstance(data.get(key), dict):
            blocks.append(data[key])
    # ~/.claude.json keeps per-project servers under projects.<path>.mcpServers.
    projects = data.get("projects")
    if isinstance(projects, dict):
        for project in projects.values():
            if isinstance(project, dict) and isinstance(project.get("mcpServers"), dict):
                blocks.append(project["mcpServers"])

    servers: list[McpServerDecl] = []
    seen: set[str] = set()
    for block in blocks:
        for name, entry in block.items():
            if name in seen:
                continue
            seen.add(name)
            entry = entry if isinstance(entry, dict) else {}
            url = str(entry.get("url") or entry.get("serverUrl") or "")
            transport = str(entry.get("type") or entry.get("transport") or "")
            if not transport:
                transport = "http" if url else "stdio"
            args = entry.get("args") or []
            servers.append(
                McpServerDecl(
                    name=str(name),
                    config=label,
                    command=str(entry.get("command") or ""),
                    args=[str(a) for a in args] if isinstance(args, list) else [],
                    url=url,
                    transport=transport,
                    headers=entry.get("headers") if isinstance(entry.get("headers"), dict) else {},
                    env=entry.get("env") if isinstance(entry.get("env"), dict) else {},
                )
            )
    return servers


def find_mcp_configs(root: Path) -> list[Path]:
    """The MCP client configs at a repository's root, in :data:`MCP_CONFIG_CANDIDATES`
    order. Only files that exist; nothing is walked below these fixed locations."""
    return [root / rel for rel in MCP_CONFIG_CANDIDATES if (root / rel).is_file()]


def _haystack(decl: McpServerDecl) -> set[str]:
    words = set(tokens(decl.name)) | {decl.name.lower()}
    for part in (decl.package, decl.url, decl.command):
        if part:
            lowered = part.lower()
            words |= set(tokens(lowered)) | {lowered}
            # "@modelcontextprotocol/server-filesystem" -> "filesystem";
            # "mcp-server-fetch" -> "fetch".
            tail = lowered.split("/")[-1].split("@")[0].split("==")[0].split(":")[0]
            words.add(tail)
            for prefix in ("server-", "mcp-server-", "mcp-"):
                if tail.startswith(prefix):
                    words.add(tail[len(prefix) :])
            for suffix in ("-mcp-server", "-mcp", "-server", "_mcp"):
                if tail.endswith(suffix):
                    words.add(tail[: -len(suffix)])
    return words


def classify_mcp_server(decl: McpServerDecl) -> Capabilities:
    """Classify a server from how it is declared. Unknown is said, never guessed."""
    words = _haystack(decl)
    for markers, flags, phrases, source, action in _KNOWN_SERVERS:
        if words & set(markers):
            return Capabilities(
                flags=set(flags),
                phrases=dict(phrases),
                data_noun=None,
                source=source,
                action=action,
            )
    if words & set(_INERT_SERVERS):
        return Capabilities()
    return Capabilities(known=False)


def server_hygiene(decl: McpServerDecl) -> list[dict[str, str]]:
    """Problems visible in the config itself, no tool list needed."""
    issues: list[dict[str, str]] = []
    if decl.url:
        if decl.url.startswith("http://") and not re.match(
            r"http://(localhost|127\.0\.0\.1|\[::1\])", decl.url
        ):
            issues.append(
                {
                    "type": "plaintext_remote",
                    "severity": "high",
                    "detail": "remote server over plain http — traffic and tokens are readable",
                }
            )
        has_auth = any(k.lower() in ("authorization", "x-api-key", "api-key") for k in decl.headers)
        if not has_auth and not re.search(r"[?&](key|token|api_key)=", decl.url):
            issues.append(
                {
                    "type": "remote_without_auth",
                    "severity": "medium",
                    "detail": "remote server with no auth header in the config — anyone "
                    "who can reach it can call it, or it relies on an OAuth login this "
                    "scan cannot see",
                }
            )
    elif decl.command and decl.pinned_version is None:
        launcher = Path(decl.command).name
        if launcher in ("npx", "pnpx", "bunx", "uvx", "pipx", "docker"):
            issues.append(
                {
                    "type": "unpinned_server",
                    "severity": "medium",
                    "detail": f"no version pinned ({launcher} fetches whatever is newest) "
                    "— its tools can change after you review them",
                }
            )
    for key, value in decl.env.items():
        text = str(value)
        if (
            text
            and not text.startswith("${")
            and re.search(r"(?:sk-|ghp_|github_pat_|xox[bpa]-|AKIA|AIza)[\w-]{8,}", text)
        ):
            issues.append(
                {
                    "type": "secret_in_config",
                    "severity": "high",
                    "detail": f"{key} holds a literal credential in the config file",
                }
            )
    broad = {"/", "~", "$HOME", "${HOME}", "/Users", "/home", "C:\\"}
    if any(arg in broad for arg in decl.args):
        issues.append(
            {
                "type": "broad_filesystem_access",
                "severity": "high",
                "detail": "given the whole disk or home directory, not a project folder",
            }
        )
    return issues


# ---------------------------------------------------------------------------
# The trifecta
# ---------------------------------------------------------------------------


@dataclass
class Member:
    """One tool or server taking part in a trifecta group."""

    name: str
    caps: Capabilities
    file: str
    line: int


def trifecta_sentence(
    label: str, members: list[Member], *, unknown: Iterable[str] = ()
) -> tuple[str, dict[str, list[str]]] | None:
    """The plain-English finding for one group, or None if the group lacks a leg.

    ``label`` names the group (a file, a directory, a config file). Returns the
    sentence and, per flag, which members supply it.
    """
    by_flag: dict[str, list[Member]] = {f: [] for f in FLAGS}
    for member in members:
        for flag in member.caps.flags:
            by_flag[flag].append(member)
    # Lead with the channel that carries data *out*: it is the one that makes the
    # sentence true, and the one the containment hint should name.
    by_flag[EXFIL].sort(key=lambda m: not (m.caps.action or "").startswith("send"))
    if not all(by_flag[f] for f in FLAGS):
        return None

    def clause(flag: str) -> str:
        # Group members that say the same thing: "can send email (send_email, reply_email)".
        groups: dict[str, list[str]] = {}
        for member in by_flag[flag]:
            phrase = member.caps.phrases.get(flag, FLAG_LABEL[flag])
            groups.setdefault(phrase, []).append(member.name)
        parts = []
        for phrase, names in list(groups.items())[:2]:
            more = ", …" if len(names) > 3 else ""
            parts.append(f"{phrase} ({', '.join(names[:3])}{more})")
        return " or ".join(parts)

    private = by_flag[PRIVATE][0].caps
    data = f"{private.data_noun} data" if private.data_noun else "private data"
    source = next((m.caps.source for m in by_flag[UNTRUSTED] if m.caps.source), "that content")
    action = next((m.caps.action for m in by_flag[EXFIL] if m.caps.action), "send {data} out")
    sentence = (
        f"{label}: {clause(PRIVATE)}, {clause(UNTRUSTED)}, and {clause(EXFIL)}. "
        f"An instruction hidden in {source} could {action.format(data=data)}."
    )
    unknown = list(unknown)
    if unknown:
        sentence += (
            f" ({len(unknown)} more server(s) here could not be classified: "
            f"{', '.join(unknown[:4])}.)"
        )
    evidence = {f: [m.name for m in by_flag[f]] for f in FLAGS}
    return sentence, evidence


def containment_hint(evidence: dict[str, list[str]], *, mcp: bool = False) -> str:
    """The next command, naming the tool that should be contained."""
    channel = (evidence.get(EXFIL) or ["<tool>"])[0]
    if mcp:
        return (
            "Contain it: don't load these servers together in one client, or put the "
            f"agent behind AgentFox and run `agentfox permit grant <agent> "
            f"mcp:{channel}/* --max-taint user` so nothing read from the web reaches "
            f"'{channel}' without an approval."
        )
    return (
        f"Contain it: `agentfox permit grant <agent> {channel} --max-taint user` "
        f"(anything derived from untrusted content needs an approval before it reaches "
        f'{channel}), or run with `agentfox.auto(mode="observe")` to watch it happen '
        "without blocking anything."
    )
