"""The delivery policies, one class per failure family.

Each family comes from a failure seen in agent runs where the model had already
produced the substance of the answer (the FIRE study, arXiv 2609.26048, catalogues
the same families on Terminal-Bench 2.1). A policy here:

* names no task, file or expected answer: eligibility reads the task's own words;
* intervenes at most ``limit`` times per session, so it cannot loop;
* writes or chooses nothing for the agent: it enforces an invariant (keep the
  evidence, detach the service, measure the bar) that lets the agent's own
  solution survive.

Families deliberately left out: LaTeX log checks and dataset token accounting.
They fixed single benchmark tasks and do not generalise to the work our users do.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, ClassVar, Literal

from agentfox.capabilities.delivery.state import SessionState

_I = re.IGNORECASE

#: Canonical tools that change a file (see ``harnesses.base.CANONICAL_TOOLS``).
_FILE_WRITES = frozenset({"file.write", "file.edit", "notebook.edit"})


@dataclass(frozen=True)
class Call:
    """One tool call, harness-neutral."""

    tool: str
    arguments: Mapping[str, Any] = field(default_factory=dict)

    @property
    def command(self) -> str:
        if self.tool != "shell":
            return ""
        return str(self.arguments.get("command") or "")

    @property
    def in_background(self) -> bool:
        """Started as a harness background task, which dies with the session."""
        return bool(self.arguments.get("run_in_background"))

    @property
    def writes_file(self) -> bool:
        return self.tool in _FILE_WRITES or bool(_SHELL_WRITE.search(self.command))


@dataclass(frozen=True)
class Stop:
    """The agent is trying to end its turn."""

    #: The harness is already continuing because a stop hook sent it back.
    reentered: bool = False
    #: Harness background tasks still running; they end with the session.
    background_tasks: tuple[str, ...] = ()


@dataclass(frozen=True)
class Nudge:
    """What a policy wants done.

    ``deny`` refuses the tool call; ``instruct`` puts ``text`` in front of the model
    (before a call, as context; at a stop, as the reason it must keep going).
    """

    action: Literal["deny", "instruct"]
    #: The policies that asked for it (more than one when a stop combines them).
    rules: tuple[str, ...]
    text: str


class Policy:
    name: ClassVar[str]
    #: Interventions allowed per session.
    limit: ClassVar[int] = 1

    def eligible(self, task: str) -> bool:
        raise NotImplementedError

    def record(self, state: SessionState, call: Call) -> None:
        """Note what a call that ran means for this policy."""

    def before_call(self, state: SessionState, call: Call) -> Nudge | None:
        return None

    def at_stop(self, state: SessionState, stop: Stop) -> Nudge | None:
        return None

    # helpers

    def _nudge(
        self, state: SessionState, action: Literal["deny", "instruct"], text: str
    ) -> Nudge | None:
        used = state.nudges.get(self.name, 0)
        if used >= self.limit:
            return None
        state.nudges[self.name] = used + 1
        return Nudge(action, (self.name,), text)


# ---------------------------------------------------------------------------
# Shared command vocabulary
# ---------------------------------------------------------------------------

_SHELL_WRITE = re.compile(
    r"\b(?:sed\s+-i|perl\s+-p?i|tee\b|truncate\b)|(?:^|[^<>&\d])>{1,2}\s*(?!&|/dev/null)\S"
    r"|\bpython3?\b[^\n]{0,200}(?:write_text|write_bytes|open\([^\n]{0,80}['\"][wa]b?['\"])",
    _I,
)

#: Commands that compare or measure, rather than change.
_MEASURE = re.compile(
    r"\b(?:git\s+diff|diff|cmp|sha\d+sum|md5sum|wc|du|stat|hyperfine|time|"
    r"pytest|py\.test|unittest|tox|nox|make\s+(?:test|check)|npm\s+(?:run\s+)?test|"
    r"cargo\s+test|go\s+test|ctest|bats)\b"
    r"|\bpython3?\b[^\n]{0,120}\b(?:test|check|verify|eval|bench|score|measure)",
    _I,
)


# ---------------------------------------------------------------------------
# 1. Service persistence
# ---------------------------------------------------------------------------


class ServicePersistence(Policy):
    """A server the task needs running after the agent leaves dies with its shell.

    Seen: the agent starts the server in its own session (or as a harness background
    task), probes it from that same session, sees it answer, and stops. The process
    is killed with the session and the verifier finds nothing listening.
    """

    name = "delivery.service_persistence"
    #: The second is only for a harness background task still alive at the stop.
    limit = 2

    _TASK = re.compile(
        r"\b(?:web\s*server|server|service|daemon|listener|endpoint|api|ssh|socket|vm|"
        r"virtual\s+machine)\b[^\n]{0,180}\b(?:run(?:s|ning)?|listen(?:s|ing)?|reachable|"
        r"available|accessible|accept(?:s|ing)?\s+connections|serv(?:e|es|ing)|"
        r"(?:be|stay|remain|keep)\s+(?:up|running|alive|online))\b"
        r"|\b(?:port|localhost:\d+|0\.0\.0\.0:\d+|127\.0\.0\.1:\d+)\b[^\n]{0,80}"
        r"\b(?:listen|running|reachable|available|serve)",
        _I,
    )
    _LAUNCH = re.compile(
        r"\b(?:qemu-system-[\w-]+|uvicorn|gunicorn|hypercorn|daphne|flask\s+run|"
        r"python[\d.]*\s+-m\s+(?:http\.server|uvicorn|flask|aiohttp\.web)|"
        r"(?:nginx|httpd|apachectl|redis-server|mongod|postgres|pg_ctl|mysqld|sshd|"
        r"dockerd|vsftpd|memcached|caddy|traefik|haproxy)\b|"
        r"npm\s+(?:start|run\s+(?:start|serve|dev))|yarn\s+(?:start|serve|dev)|"
        r"node\s+\S*(?:server|app|index|main)\.[cm]?js|"
        r"python[\d.]*\s+\S*(?:server|serve|service|daemon|app|main|api|grpc)[\w-]*\.py|"
        r"java\s+-jar|rails\s+s(?:erver)?|php\s+-S|docker(?:\s+compose)?\s+(?:run|up)|"
        r"systemctl\s+(?:start|restart)|service\s+\S+\s+(?:start|restart))",
        _I,
    )
    _DETACHED = re.compile(
        r"\bsetsid\b|\bnohup\b[^\n]*&|\bdisown\b|\bsystemd-run\b|"
        r"\bsystemctl\s+(?:start|restart)\b|\bservice\s+\S+\s+(?:start|restart)\b|"
        r"\btmux\s+new(?:-session)?\b[^\n]*\s-d|\bscreen\s+-d?m|\bstart-stop-daemon\b|"
        r"\bdocker(?:\s+compose)?\s+(?:run|up)\b[^\n]*\s(?:-d|--detach)\b|"
        r"--daemon(?:ize)?\b|daemonize\s+yes|\bpg_ctl\b[^\n]*\bstart\b|"
        r"\b(?:nginx|httpd|apachectl|sshd|dockerd)\b(?![^\n]*daemon\s+off)|"
        r"\b(?:pm2|supervisorctl|forever)\s+start\b",
        _I,
    )
    _PROBE = re.compile(
        r"\b(?:curl|wget|grpcurl|httpie|http\s+(?:get|post)|nc\s+-[a-z]*z|ncat|telnet|ssh|"
        r"sshpass|ss\s+-[a-z]*l|netstat|lsof\s+-i|redis-cli|pg_isready|mysqladmin\s+ping)\b"
        r"|socket\.create_connection|requests\.(?:get|post|head)|urlopen|"
        r"channel_ready_future|http\.client",
        _I,
    )

    def eligible(self, task: str) -> bool:
        return bool(self._TASK.search(task))

    def record(self, state: SessionState, call: Call) -> None:
        cmd = call.command
        if not cmd:
            return
        if self._LAUNCH.search(cmd):
            state.mark("launch")
            if call.in_background:
                state.mark("background_launch")
            elif self._DETACHED.search(cmd):
                state.mark("detached")
        # A probe chained into the launch command proves only that the server was
        # up while the launching shell was; it has to come from a later call.
        if self._PROBE.search(cmd) and not self._LAUNCH.search(cmd):
            state.mark("probe")

    def at_stop(self, state: SessionState, stop: Stop) -> Nudge | None:
        if not state.at("launch"):
            return None
        # A harness background task the agent launched is still alive: it dies with
        # the session, and any probe since may have reached it instead of the copy
        # that was meant to outlive it. Seen live: on macOS `setsid` does not exist,
        # the "detached" relaunch failed into its log, and the probe passed against
        # the background task. So this case may send the agent back a second time.
        attached = bool(stop.background_tasks) and state.at("background_launch") > 0
        detached = state.at("detached") >= state.at("launch")
        probed = state.after("probe", "launch")
        if detached and probed and not attached:
            return None
        if state.nudges.get(self.name, 0) >= 1 and not attached:
            return None
        if attached and state.nudges.get(self.name, 0) >= 1:
            text = (
                "These background tasks of this session are still running and will be "
                "killed when it ends: " + "; ".join(stop.background_tasks[:3]) + ". A "
                "probe since then may have reached them rather than a detached copy. Stop "
                "them, confirm the port is free, start the service detached, read its log "
                "to confirm it actually started, and probe it again from a later command."
            )
        else:
            text = (
                "The task needs a service that is still running after you finish, and you "
                "started one. A process launched from this session, including a background "
                "task of this tool, is killed when the session ends. Stop that copy first "
                "(it holds the port, so a probe would reach it), then start the service "
                "detached from this shell with every standard stream redirected: "
                "`nohup <command> > /tmp/service.log 2>&1 < /dev/null & disown` works in "
                "bash and zsh on Linux and macOS (`setsid` does not exist on macOS), or use "
                "the system's service manager. Read the log to confirm it started, then "
                "probe the port or endpoint the task names from a separate, later command. "
                "If a detached launch already passes that later probe, stop without "
                "changing it."
            )
        return self._nudge(state, "instruct", text)


# ---------------------------------------------------------------------------
# 2. Evidence preservation
# ---------------------------------------------------------------------------


class EvidencePreservation(Policy):
    """On a recovery task, the damaged original is the evidence. Copy it first.

    Seen: the agent opens the only copy of a damaged SQLite database to look at it.
    Opening it replays and removes the write-ahead log, which was the only place the
    lost rows still existed.
    """

    name = "delivery.evidence_preservation"
    #: Repeats: one warning followed by an incomplete copy must not unlock the
    #: destructive open. Capped so a copy our patterns do not recognise cannot
    #: deadlock the agent.
    limit = 3

    _TASK = re.compile(
        r"\b(?:corrupt\w*|damaged|recover\w*|repair\w*|forensic\w*|salvage\w*|"
        r"truncated|deleted|lost|undelete|restore\s+(?:the\s+)?(?:lost|deleted))\b",
        _I,
    )
    _DATABASE = re.compile(r"\b(?:database|sqlite\w*|wal|\.db)\b", _I)
    _BACKUP = re.compile(r"\b(?:cp|rsync|tar|dd|cpio|zip|ditto)\b", _I)
    #: A database copy counts only if it keeps the sidecars: copying just ``main.db``
    #: and then opening it still replays and deletes ``main.db-wal``.
    _DB_BACKUP = re.compile(
        r"\b(?:cp|rsync)\b[^\n]*(?:\s-[a-zA-Z]*[raR][a-zA-Z]*\b|\*|\{[^}]*\}|-wal\b|-shm\b|"
        r"-journal\b)|\b(?:tar|zip|cpio|ditto)\b",
        _I,
    )
    _MUTATING_OPEN = re.compile(
        r"\bsqlite3\s+(?!-readonly\b)[^\s|;&]+(?![^\n]*mode=ro)|"
        r"\bpython[\d.]*\b[^\n]{0,1000}\bsqlite3\.connect\((?![^)]*mode=ro)|"
        r"\b(?:e2)?fsck\b(?![^\n]*\s-n\b)|\bmount\b(?![^\n]*\bro\b)|\btruncate\b|"
        r"\bgit\s+(?:checkout|reset|clean|gc|prune|stash)\b|\bunzip\b[^\n]*\s-o\b|"
        r"\b(?:mysql|psql|mongo|mongosh|redis-cli)\b",
        _I,
    )

    def eligible(self, task: str) -> bool:
        return bool(self._TASK.search(task))

    def record(self, state: SessionState, call: Call) -> None:
        cmd = call.command
        if not cmd or not self._BACKUP.search(cmd):
            return
        if "database" not in state.flags or self._DB_BACKUP.search(cmd):
            state.mark("backup")

    def before_call(self, state: SessionState, call: Call) -> Nudge | None:
        cmd = call.command
        if not cmd or state.at("backup") or self._BACKUP.search(cmd):
            return None
        if not self._MUTATING_OPEN.search(cmd):
            return None
        return self._nudge(
            state,
            "deny",
            "This is a recovery task and the original evidence has not been preserved "
            "yet. This command can change it while opening or repairing it (a database "
            "open, for one, replays and deletes its write-ahead log). First make a "
            "byte-for-byte copy of the artifact together with its sidecar files (for "
            "example `cp -a` of the whole directory), then work on the copy, and inspect "
            "the original only with a read-only reader or a hex dump.",
        )


# ---------------------------------------------------------------------------
# 3. Deployment preservation
# ---------------------------------------------------------------------------


class DeploymentPreservation(Policy):
    """Once a deployment has been checked and works, do not tear it down tidying up.

    Seen: the agent pushes, confirms the page is served, then "cleans up" with a
    reset or by deleting the work tree the server was serving from.
    """

    name = "delivery.deployment_preservation"
    limit = 2

    _TASK = re.compile(
        r"\b(?:deploy(?:s|ed|ing|ment)?|post-receive|bare\s+(?:git\s+)?repo(?:sitory)?|"
        r"git\s+server|publish(?:es|ed)?\s+(?:to|on)|served\s+(?:at|from|on))\b",
        _I,
    )
    _PROBE = re.compile(r"\bgit\s+push\b|\b(?:curl|wget)\b", _I)
    _DESTROY = re.compile(
        r"\bgit\b[^\n]*\b(?:reset\s+--hard|clean\s+-[a-z]*f|update-ref\s+-d|branch\s+-D|"
        r"push\b[^\n]*(?:--force|\s-f\b|--delete|\s:\S))|"
        r"\brm\s+-[a-zA-Z]*r[a-zA-Z]*\b[^\n]*(?:/var/www|/srv\b|\.git\b|\bhooks?\b)|"
        r"\bdocker(?:\s+compose)?\s+(?:rm\s+-f|down|stop|kill)\b",
        _I,
    )

    def eligible(self, task: str) -> bool:
        return bool(self._TASK.search(task))

    def record(self, state: SessionState, call: Call) -> None:
        if call.command and self._PROBE.search(call.command):
            state.mark("deployment.probe")

    def before_call(self, state: SessionState, call: Call) -> Nudge | None:
        cmd = call.command
        if not cmd or not state.at("deployment.probe") or not self._DESTROY.search(cmd):
            return None
        return self._nudge(
            state,
            "deny",
            "The deployment was already exercised (a push or a request against it), and "
            "this command would remove or rewrite deployed state. Leave the tested "
            "branch, commits, deployed files, document root and running server as they "
            "are: the evaluator checks that final state. Narrow the command to clearly "
            "temporary data if cleanup is really needed.",
        )


# ---------------------------------------------------------------------------
# 4. Exact replacement
# ---------------------------------------------------------------------------


class ExactReplacement(Policy):
    """A closed replacement map, with everything else protected.

    Seen: the agent makes exactly the requested substitutions, then reformats the
    file, changes quoting, or drops the trailing newline, and the byte-level check
    fails on content it was told to leave alone.
    """

    name = "delivery.exact_replacement"
    limit = 2

    _REPLACE = re.compile(
        r"\b(?:replac(?:e|ing)|substitut(?:e|ing)|redact|sanitiz(?:e|ing)|scrub|rename\s+all|"
        r"placeholder)\b",
        _I,
    )
    _PROTECT = re.compile(
        r"\b(?:do\s+not|don't|must\s+not|never)\s+(?:modify|change|edit|touch|alter|reformat)|"
        r"\bleave\b[^\n]{0,80}\b(?:unchanged|intact|as\s+is)\b|"
        r"\bonly\s+(?:modify|change|edit|replace)\b|\bnothing\s+else\b|"
        r"\b(?:exact(?:ly)?|byte-for-byte|verbatim)\b",
        _I,
    )
    _SECRET = re.compile(
        r"\b(?:api\s+keys?|access\s+keys?|secret\s+keys?|tokens?|credentials?|passwords?)\b", _I
    )

    def eligible(self, task: str) -> bool:
        return bool(self._REPLACE.search(task) and self._PROTECT.search(task))

    def record(self, state: SessionState, call: Call) -> None:
        if call.writes_file:
            state.mark("write")
        if call.command and _MEASURE.search(call.command):
            state.mark("check")

    def before_call(self, state: SessionState, call: Call) -> Nudge | None:
        if not call.writes_file or state.at("write") or state.nudges.get(self.name):
            return None
        return self._nudge(
            state,
            "instruct",
            "This task gives a closed set of replacements and protects everything else. "
            "Treat the map as a byte-level allowlist: change only the listed tokens, and "
            "never whitespace, punctuation, quoting, line endings or a file's final "
            "newline unless the map lists it. Keep a record of each source-to-target pair "
            "so the final diff can be checked mechanically.",
        )

    def at_stop(self, state: SessionState, stop: Stop) -> Nudge | None:
        if not state.at("write") or state.after("check", "write"):
            return None
        secret = "credential" in state.flags
        return self._nudge(
            state,
            "instruct",
            "Before finishing, check the final diff mechanically rather than by eye: every "
            "changed token must map to a listed replacement, and whitespace, token count "
            "and each file's end-of-file newline must be unchanged elsewhere. "
            + (
                "Search every working-tree file, including ignored and generated ones, "
                "for each original credential value and confirm none remains. "
                if secret
                else ""
            )
            + "Then run the task's own end-to-end check. If the diff and the check already "
            "pass, stop without rewriting anything.",
        )


# ---------------------------------------------------------------------------
# 5. Complete enumeration
# ---------------------------------------------------------------------------


class Enumeration(Policy):
    """The task wants every valid answer; the agent returns the first one it finds."""

    name = "delivery.enumerate_all"

    _MULTIPLE = re.compile(
        r"\b(?:all|every|each|multiple|more\s+than\s+one)\b[^\n]{0,100}\b(?:valid|winning|"
        r"correct|acceptable|possible|matching)\b[^\n]{0,80}\b(?:moves?|answers?|solutions?|"
        r"results?|values?|combinations?|candidates?)\b",
        _I,
    )
    _EACH = re.compile(
        r"\b(?:one\s+per\s+line|each\s+on\s+(?:a|its\s+own)\s+line|print\s+them\s+all|"
        r"write\s+them\s+all|output\s+them\s+all|list\s+(?:them\s+)?all)\b",
        _I,
    )

    def eligible(self, task: str) -> bool:
        return bool(self._MULTIPLE.search(task) and self._EACH.search(task))

    def at_stop(self, state: SessionState, stop: Stop) -> Nudge | None:
        return self._nudge(
            state,
            "instruct",
            "The output must contain every valid answer, not one example. Enumerate the "
            "full candidate set, test each candidate against the task's condition, remove "
            "duplicates, and write all survivors in the exact one-per-line format "
            "requested. Before stopping, confirm no other candidate satisfies the "
            "condition.",
        )


# ---------------------------------------------------------------------------
# 6. Measured acceptance bar
# ---------------------------------------------------------------------------


class MeasuredAcceptance(Policy):
    """The task states a number the result must meet; the agent never measures it.

    Seen: a size, latency or accuracy bar in the task text, an artifact that looks
    right, and a stop with no measurement after the last change.
    """

    name = "delivery.measured_acceptance"

    _BAR = re.compile(
        r"\b(?:at\s+most|under|less\s+than|fewer\s+than|no\s+more\s+than|below|within|"
        r"at\s+least|more\s+than|greater\s+than|above|faster\s+than|smaller\s+than)\s+"
        r"\d[\d,.]*\s*(?:%|percent|ms|milliseconds?|s|secs?|seconds?|minutes?|bytes?|"
        r"[kmg]i?b|lines?|tokens?|characters?|chars?)(?![\w])",
        _I,
    )

    def eligible(self, task: str) -> bool:
        return bool(self._BAR.search(task))

    def record(self, state: SessionState, call: Call) -> None:
        if call.writes_file:
            state.mark("write")
        if call.command and _MEASURE.search(call.command):
            state.mark("measure")

    def at_stop(self, state: SessionState, stop: Stop) -> Nudge | None:
        if not state.at("write") or state.after("measure", "write"):
            return None
        return self._nudge(
            state,
            "instruct",
            "The task states a measurable acceptance bar, and nothing has measured the "
            "final artifact since the last change. Measure it now with the same build and "
            "invocation the task describes, and compare the actual number with the bar. "
            "If it misses, change the approach rather than calling it close enough; if it "
            "passes, stop.",
        )


#: Every policy, in the order a stop combines their instructions.
POLICIES: tuple[Policy, ...] = (
    ServicePersistence(),
    EvidencePreservation(),
    DeploymentPreservation(),
    ExactReplacement(),
    Enumeration(),
    MeasuredAcceptance(),
)
_BY_NAME = {p.name: p for p in POLICIES}

#: Facts about the task that refine a policy without making it eligible on their own.
_FLAGS = {
    "database": EvidencePreservation._DATABASE,
    "credential": ExactReplacement._SECRET,
}


# ---------------------------------------------------------------------------
# The three moments
# ---------------------------------------------------------------------------


def on_task(state: SessionState, task: str) -> list[str]:
    """Read the task text once; returns the policies that became eligible."""
    added = [p.name for p in POLICIES if p.name not in state.eligible and p.eligible(task)]
    state.eligible.extend(added)
    for flag, pattern in _FLAGS.items():
        if flag not in state.flags and pattern.search(task):
            state.flags.append(flag)
    return added


def before_call(state: SessionState, call: Call) -> Nudge | None:
    """A refusal or an instruction for a call about to run, or None."""
    for name in state.eligible:
        nudge = _BY_NAME[name].before_call(state, call)
        if nudge is not None:
            return nudge
    return None


def after_call(state: SessionState, call: Call) -> None:
    """Record a call that ran."""
    state.seq += 1
    for name in state.eligible:
        _BY_NAME[name].record(state, call)


def at_stop(state: SessionState, stop: Stop) -> Nudge | None:
    """Every due instruction, combined into one, or None to let the agent stop."""
    due = [n for name in state.eligible if (n := _BY_NAME[name].at_stop(state, stop))]
    if not due:
        return None
    if len(due) == 1:
        return due[0]
    text = "\n\n".join(f"{i}. {n.text}" for i, n in enumerate(due, 1))
    rules = tuple(rule for n in due for rule in n.rules)
    return Nudge("instruct", rules, "Before finishing:\n\n" + text)


__all__ = [
    "POLICIES",
    "Call",
    "Nudge",
    "Policy",
    "Stop",
    "after_call",
    "at_stop",
    "before_call",
    "on_task",
]
